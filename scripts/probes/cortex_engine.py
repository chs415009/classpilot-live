"""DSPy custom engine over AI_COMPLETE, shared by the Route B probes."""

import json
import warnings

from dspy import lm15

warnings.filterwarnings("ignore")
SQL = (
    "SELECT AI_COMPLETE(model => %s, prompt => %s, "
    "model_parameters => {'temperature': 0, 'max_tokens': 1024}, "
    "return_error_details => TRUE)"
)


def flatten(request) -> str:
    parts = [f"System:\n{request.system}"] if request.system else []
    for m in request.messages:
        parts.append(f"{m.role.capitalize()}:\n{m.text}")
    return "\n\n".join(parts)


class CortexCompleteEngine:
    def __init__(self, connection, timeout_s: int):
        self.connection, self.timeout_s, self.calls = connection, timeout_s, []

    def complete(self, request):
        prompt = flatten(request)
        cur = self.connection.cursor()
        try:
            row = cur.execute(SQL, (request.model, prompt), timeout=self.timeout_s).fetchone()
        except Exception as exc:
            msg = str(exc)
            if "604" in msg or "cancel" in msg.lower() or "timeout" in msg.lower():
                raise lm15.TimeoutError(msg[:200]) from exc
            raise lm15.ServerError(msg[:200]) from exc
        finally:
            cur.close()
        result = json.loads(row[0]) if row and row[0] else {}
        self.calls.append({"prompt_chars": len(prompt), "error": result.get("error")})
        if result.get("error") or result.get("value") is None:
            raise lm15.ServerError(f"AI_COMPLETE error: {result.get('error')}")
        value = result["value"]
        text = value if isinstance(value, str) else json.dumps(value)
        return lm15.Response(
            id=None,
            model=request.model,
            message=lm15.Message.assistant(text),
            finish_reason="stop",
            usage=lm15.Usage(),
        )
