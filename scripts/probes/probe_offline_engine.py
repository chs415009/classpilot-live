"""Offline (no network): what a custom DSPy engine receives from ChatAdapter and
JSONAdapter, and how malformed output and engine errors surface to the caller."""

import warnings

import dspy
from dspy import lm15

from common import QUESTION, Analyst, objectives_text, save, timed

warnings.filterwarnings("ignore")


class RecordingEngine:
    def __init__(self, reply: str | None = None, error: Exception | None = None):
        self.reply, self.error, self.requests = reply, error, []

    def complete(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        return lm15.Response(
            id=None, model=request.model, message=lm15.Message.assistant(self.reply),
            finish_reason="stop", usage=lm15.Usage(),
        )


def run(engine, adapter):
    lm = dspy.LM("probe", engine=engine, cache=False, num_retries=0)
    with dspy.context(lm=lm, adapter=adapter):
        return dspy.Predict(Analyst)(objectives=objectives_text(), question=QUESTION)


GOOD_JSON = '{"category": "in_scope", "objective_id": "objective-02", "reason": "About Bronze."}'
GOOD_CHAT = (
    "[[ ## category ## ]]\nin_scope\n\n[[ ## objective_id ## ]]\nobjective-02\n\n"
    "[[ ## reason ## ]]\nAbout Bronze.\n\n[[ ## completed ## ]]"
)
results = {}
for name, adapter, reply in [
    ("chat_good", dspy.ChatAdapter(use_json_adapter_fallback=False), GOOD_CHAT),
    ("json_good", dspy.JSONAdapter(), GOOD_JSON),
    ("chat_malformed", dspy.ChatAdapter(use_json_adapter_fallback=False), "sorry, no idea"),
    ("json_malformed", dspy.JSONAdapter(), "not json at all"),
    ("chat_bad_literal", dspy.ChatAdapter(use_json_adapter_fallback=False),
     GOOD_CHAT.replace("in_scope", "maybe")),
]:
    engine = RecordingEngine(reply=reply)
    pred, err, _ = timed(run, engine, adapter)
    req = engine.requests[0] if engine.requests else None
    results[name] = {
        "calls": len(engine.requests),
        "prediction": dict(pred) if pred else None,
        "error": err,
        "response_format": getattr(req.config, "response_format", None) if req else None,
        "system_prompt_head": (req.system or "")[:300] if req else None,
        "roles": [m.role for m in req.messages] if req else None,
    }

for name, exc in [
    ("engine_timeout", lm15.TimeoutError("probe timeout")),
    ("engine_server_error", lm15.ServerError("probe 503")),
    ("engine_value_error", ValueError("probe bug")),
]:
    engine = RecordingEngine(error=exc)
    _, err, _ = timed(run, engine, dspy.ChatAdapter(use_json_adapter_fallback=False))
    results[name] = {"calls": len(engine.requests), "error": err}

print(save("offline_engine", results))
for k, v in results.items():
    print(k, "| calls", v["calls"], "| error:", v.get("error"), "| pred:", v.get("prediction"))
print("json response_format:", results["json_good"]["response_format"])
print("chat response_format:", results["chat_good"]["response_format"])
