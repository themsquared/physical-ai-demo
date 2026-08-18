"""Identity loading: each agent's JWT comes from the shared demo tokens file.

JWT_TOKEN env wins (explicit override); otherwise read JWT_TOKEN_FILE (the
tokens.json produced by scripts/gen-jwts.py, mounted read-only) keyed by
identity name.
"""

import json
import os


def load_token(identity: str) -> str:
    if os.environ.get("JWT_TOKEN"):
        return os.environ["JWT_TOKEN"]
    path = os.environ.get("JWT_TOKEN_FILE", "/jwt/tokens.json")
    try:
        with open(path) as f:
            return json.load(f)[identity]
    except (OSError, KeyError, json.JSONDecodeError):
        return ""
