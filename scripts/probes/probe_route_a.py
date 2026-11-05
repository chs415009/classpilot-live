"""Route A probe (live, about 4-5 LLM calls): Cortex REST with a key-pair JWT signed with
`cryptography` (no PyJWT), listing models, DSPy over LiteLLM's snowflake provider, a
forced client timeout, and one direct REST call with response_format on a Claude model.
The token is never printed or saved."""

import base64
import hashlib
import json
import os
import time
import warnings
from pathlib import Path

import dspy
import requests
from common import QUESTION, Analyst, model_name, objectives_text, save, timed
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

warnings.filterwarnings("ignore")


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_jwt(lifetime_s: int = 3000) -> str:
    key = serialization.load_pem_private_key(
        Path(os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"]).expanduser().read_bytes(),
        password=(os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSWORD") or "").encode() or None,
    )
    pub_der = key.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    fingerprint = "SHA256:" + base64.b64encode(hashlib.sha256(pub_der).digest()).decode()
    account = os.environ["SNOWFLAKE_ACCOUNT"].upper().replace(".", "-")
    user = os.environ["SNOWFLAKE_USER"].upper()
    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT"}
    payload = {
        "iss": f"{account}.{user}.{fingerprint}",
        "sub": f"{account}.{user}",
        "iat": now,
        "exp": now + lifetime_s,
    }
    signing_input = f"{b64url(json.dumps(header).encode())}.{b64url(json.dumps(payload).encode())}"
    signature = key.sign(signing_input.encode(), padding.PKCS1v15(), hashes.SHA256())
    return f"{signing_input}.{b64url(signature)}"


def base_url() -> str:
    host = os.environ["SNOWFLAKE_ACCOUNT"].lower().replace("_", "-")
    return f"https://{host}.snowflakecomputing.com"


common_mod_env = model_name()  # loads .env
token = make_jwt()
headers = {
    "Authorization": f"Bearer {token}",
    "Content-Type": "application/json",
    "Accept": "application/json",
    "X-Snowflake-Authorization-Token-Type": "KEYPAIR_JWT",
}
results = {}

# 1. Model list (not an LLM call).
resp, err, secs = timed(
    requests.get, f"{base_url()}/api/v2/cortex/models", headers=headers, timeout=20
)
results["models"] = {
    "status": resp.status_code if resp is not None else None,
    "error": err,
    "seconds": secs,
    "body": (
        resp.json()
        if resp is not None and resp.ok
        else (resp.text[:300] if resp is not None else None)
    ),
}

# 2. DSPy over LiteLLM, one Analyst call per adapter.
os.environ["SNOWFLAKE_JWT"] = token
os.environ["SNOWFLAKE_ACCOUNT_ID"] = os.environ["SNOWFLAKE_ACCOUNT"]
for name, adapter in [
    ("litellm_chat", dspy.ChatAdapter(use_json_adapter_fallback=False)),
    ("litellm_json", dspy.JSONAdapter()),
]:
    lm = dspy.LM(
        f"snowflake/{model_name()}",
        engine="litellm",
        cache=False,
        num_retries=0,
        temperature=0,
        max_tokens=1024,
        api_base=base_url(),
        timeout=10,
    )

    def ask(lm=lm, adapter=adapter):
        with dspy.context(lm=lm, adapter=adapter):
            return dspy.Predict(Analyst)(objectives=objectives_text(), question=QUESTION)

    pred, err, secs = timed(ask)
    results[name] = {
        "prediction": dict(pred) if pred else None,
        "error": err and err[:400],
        "seconds": secs,
    }

# 3. Forced client timeout through LiteLLM (long free-text request, 2 s).
lm = dspy.LM(
    f"snowflake/{model_name()}",
    engine="litellm",
    cache=False,
    num_retries=0,
    max_tokens=1024,
    api_base=base_url(),
    timeout=2,
)
out, err, secs = timed(lm, "Write a detailed 1500-word essay about data warehouse history.")
results["litellm_timeout"] = {"error": err and err[:300], "seconds": secs, "got_output": bool(out)}

# 4. Direct REST chat completion with response_format (json_schema) on a Claude model.
schema = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "objective_id", "reason"],
    "properties": {
        "category": {"type": "string", "enum": ["in_scope", "out_of_scope", "assignment_like"]},
        "objective_id": {"type": ["string", "null"]},
        "reason": {"type": "string"},
    },
}
body = {
    "model": os.environ.get("PROBE_VISION_MODEL", "claude-haiku-4-5"),
    "messages": [
        {
            "role": "user",
            "content": f"Lesson objectives:\n{objectives_text()}\n\nClassify: {QUESTION}",
        }
    ],
    "max_completion_tokens": 300,
    "response_format": {
        "type": "json_schema",
        "json_schema": {"name": "analyst", "schema": schema},
    },
}
resp, err, secs = timed(
    requests.post,
    f"{base_url()}/api/v2/cortex/v1/chat/completions",
    headers=headers,
    json=body,
    timeout=20,
)
content = None
if resp is not None and resp.ok:
    content = resp.json()["choices"][0]["message"]["content"]
results["rest_claude_json_schema"] = {
    "model": body["model"],
    "status": resp.status_code if resp is not None else None,
    "error": err,
    "seconds": secs,
    "content": content,
    "body_if_error": None if (resp is None or resp.ok) else resp.text[:400],
}

path = save("route_a", results)
print(path)
summary = {
    k: ({kk: vv for kk, vv in v.items() if kk != "body"} if isinstance(v, dict) else v)
    for k, v in results.items()
}
print(json.dumps(summary, indent=2, default=str)[:4000])
m = results["models"]["body"]
print("models type:", type(m).__name__, "| sample:", json.dumps(m)[:600] if m else None)
