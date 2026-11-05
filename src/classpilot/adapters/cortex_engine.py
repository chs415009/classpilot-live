"""Route B: a DSPy 3.4 custom engine over Snowflake Cortex AI_COMPLETE.

Stage 1 findings this follows (docs/agent/note.md):
- Cortex REST (Route A) is blocked on the current account, so every LLM call goes
  through AI_COMPLETE on the connector connection.
- The connector's per-query `timeout=` does not cancel AI_COMPLETE.
  `ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS` does (error 000630), so the engine
  sets it once on its connection. `call_llm`'s thread timeout is the backstop.
- Live calls use `num_retries=0` and `cache=False`, so one prediction is one call.

The DSPy adapter writes the prompt; the engine flattens it into the single prompt
string AI_COMPLETE takes. No `response_format`: DSPy parses the text reply.
"""

import json
import math

import dspy
from dspy import lm15

from classpilot.settings import Settings

# max_tokens is an int from code, formatted in; model and prompt are bind variables.
COMPLETE_SQL = (
    "SELECT AI_COMPLETE(model => %s, prompt => %s, "
    "model_parameters => {{'temperature': 0, 'max_tokens': {max_tokens}}}, "
    "return_error_details => TRUE)"
)
TIMEOUT_CODES = ("000630", "000604")  # statement timeout, statement canceled


def flatten(request: lm15.Request) -> str:
    system = request.system
    if isinstance(system, tuple):  # prompt parts; keep their text
        system = "\n".join(getattr(part, "text", "") or "" for part in system)
    parts = [f"System:\n{system}"] if system else []
    for message in request.messages:
        parts.append(f"{message.role.capitalize()}:\n{message.text}")
    return "\n\n".join(parts)


class CortexCompleteEngine:
    """`complete(Request) -> Response` over AI_COMPLETE."""

    def __init__(self, connection, timeout_s: float, max_tokens: int = 1024):
        self.connection = connection
        self.sql = COMPLETE_SQL.format(max_tokens=int(max_tokens))
        seconds = max(1, math.ceil(timeout_s))
        cursor = connection.cursor()
        try:
            cursor.execute(f"ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = {seconds}")
        finally:
            cursor.close()

    def complete(self, request: lm15.Request) -> lm15.Response:
        cursor = self.connection.cursor()
        try:
            row = cursor.execute(self.sql, (request.model, flatten(request))).fetchone()
        except Exception as exc:
            message = str(exc)[:200]
            if any(code in message for code in TIMEOUT_CODES):
                raise lm15.TimeoutError(message) from exc
            raise lm15.ServerError(message) from exc
        finally:
            cursor.close()

        result = json.loads(row[0]) if row and row[0] is not None else None
        if not isinstance(result, dict) or result.get("error") or result.get("value") is None:
            error = result.get("error") if isinstance(result, dict) else "no result"
            raise lm15.ServerError(f"AI_COMPLETE error: {error}")
        value = result["value"]
        text = value if isinstance(value, str) else json.dumps(value)
        return lm15.Response(
            id=None,
            model=request.model,
            message=lm15.Message.assistant(text),
            finish_reason="stop",
            usage=lm15.Usage(),
        )


def make_cortex_lm(settings: Settings, connection=None) -> dspy.LM:
    if not settings.llm.model:
        raise ValueError("Set llm.model in config/settings.yaml for BACKEND=cortex.")
    if connection is None:
        from classpilot.adapters.snowflake import shared_connection

        connection = shared_connection()
    engine = CortexCompleteEngine(connection, settings.llm.timeout_seconds)
    return dspy.LM(settings.llm.model, engine=engine, cache=False, num_retries=0)
