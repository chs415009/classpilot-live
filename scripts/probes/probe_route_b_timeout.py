"""Route B forced timeout (live, 1 AI_COMPLETE call): a long free-text request with a
1 s query timeout, called through dspy.LM without an adapter."""

import warnings

import dspy
from common import model_name, save, timed
from cortex_engine import CortexCompleteEngine

from classpilot.adapters.snowflake import shared_connection

warnings.filterwarnings("ignore")

engine = CortexCompleteEngine(shared_connection(), timeout_s=1)
lm = dspy.LM(model_name(), engine=engine, cache=False, num_retries=0, max_tokens=1024)
out, err, secs = timed(lm, "Write a detailed 1500-word essay about data warehouse history.")
result = {"error": err, "seconds": secs, "got_output": bool(out)}
print(save("route_b_timeout", result))
print(result)
