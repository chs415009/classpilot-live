"""Route B probe (live, about 3 AI_COMPLETE calls): a DSPy custom engine over the
existing AI_COMPLETE connection. One Analyst call per adapter, plus a forced timeout."""

import json
import warnings

import dspy

from classpilot.adapters.snowflake import shared_connection
from common import QUESTION, Analyst, model_name, objectives_text, save, timed
from cortex_engine import CortexCompleteEngine

warnings.filterwarnings("ignore")


def ask(engine, adapter, question=QUESTION):
    lm = dspy.LM(model_name(), engine=engine, cache=False, num_retries=0)
    with dspy.context(lm=lm, adapter=adapter):
        return dspy.Predict(Analyst)(objectives=objectives_text(), question=question)


conn = shared_connection()
results = {"model": model_name()}
for name, adapter in [
    ("chat", dspy.ChatAdapter(use_json_adapter_fallback=False)),
    ("json", dspy.JSONAdapter()),
]:
    engine = CortexCompleteEngine(conn, timeout_s=10)
    pred, err, secs = timed(ask, engine, adapter)
    results[name] = {"prediction": dict(pred) if pred else None, "error": err,
                     "seconds": secs, "calls": engine.calls}

engine = CortexCompleteEngine(conn, timeout_s=1)
long_q = "Write a 2000-word essay on every layer of the medallion architecture. " + QUESTION
pred, err, secs = timed(ask, engine, dspy.ChatAdapter(use_json_adapter_fallback=False), long_q)
results["forced_timeout"] = {"error": err, "seconds": secs, "prediction": dict(pred) if pred else None}

print(save("route_b", results))
print(json.dumps(results, indent=2, default=str))
