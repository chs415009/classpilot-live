"""Snowflake connection for the Cortex adapters and the setup scripts.

Reads credentials from .env (key-pair auth). Needs the optional extra:
    pip install -e ".[dev,snowflake]"
"""

import atexit
import os
from functools import lru_cache
from pathlib import Path

from classpilot.settings import PROJECT_ROOT

REQUIRED_VARS = [
    "SNOWFLAKE_ACCOUNT",
    "SNOWFLAKE_USER",
    "SNOWFLAKE_PRIVATE_KEY_FILE",
    "SNOWFLAKE_ROLE",
    "SNOWFLAKE_WAREHOUSE",
    "SNOWFLAKE_DATABASE",
    "SNOWFLAKE_SCHEMA",
]


def load_env(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load KEY=VALUE lines into os.environ. Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _read_private_key(path: str, password: str | None) -> bytes:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_private_key(
        Path(path).expanduser().read_bytes(),
        password=password.encode() if password else None,
    )
    return key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def connect():
    """Open a new connection. Raises RuntimeError if .env is incomplete."""
    load_env()
    missing = [name for name in REQUIRED_VARS if not os.environ.get(name)]
    if missing:
        raise RuntimeError(f"Missing in .env: {', '.join(missing)}")

    import snowflake.connector

    return snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ["SNOWFLAKE_USER"],
        private_key=_read_private_key(
            os.environ["SNOWFLAKE_PRIVATE_KEY_FILE"],
            os.environ.get("SNOWFLAKE_PRIVATE_KEY_PASSWORD") or None,
        ),
        role=os.environ["SNOWFLAKE_ROLE"],
        warehouse=os.environ["SNOWFLAKE_WAREHOUSE"],
        database=os.environ["SNOWFLAKE_DATABASE"],
        schema=os.environ["SNOWFLAKE_SCHEMA"],
        login_timeout=30,
        # Always log out on close; we never leave async queries running.
        enable_server_session_keep_alive_auto_detection=False,
    )


@lru_cache(maxsize=1)
def shared_connection():
    """One connection per process, shared by the LLM and search adapters."""
    connection = connect()
    atexit.register(connection.close)
    return connection
