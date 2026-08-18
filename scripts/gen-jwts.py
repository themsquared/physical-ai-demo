#!/usr/bin/env python3
"""Generate demo JWT material: RSA keypair, JWKS, and one static token per identity.

Demo-only credentials — regenerated on setup, never committed (see .gitignore).
Identities are the security boundary of the whole demo: the CEL envelope in
gateway/config.yaml keys off `sub`.

Usage: python scripts/gen-jwts.py [outdir]   (deps: pyjwt, cryptography)
"""

import json
import sys
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

IDENTITIES = [
    "orchestrator",
    "amr-1-cognition",
    "amr-2-cognition",
    "arm-1-cognition",
    "maintenance",
]
ISSUER = "physical-ai-demo"
AUDIENCE = "agentgateway"
TEN_YEARS = 10 * 365 * 24 * 3600  # demo tokens; rotation is out of scope (PRD non-goal)


def main(outdir: str) -> None:
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    (out / "signing.key").write_bytes(priv_pem)

    jwk = json.loads(RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": "demo-key", "alg": "RS256", "use": "sig"})
    (out / "jwks.json").write_text(json.dumps({"keys": [jwk]}, indent=2))

    now = int(time.time())
    tokens = {
        sub: jwt.encode(
            {"sub": sub, "iss": ISSUER, "aud": AUDIENCE, "iat": now, "exp": now + TEN_YEARS},
            priv_pem,
            algorithm="RS256",
            headers={"kid": "demo-key"},
        )
        for sub in IDENTITIES
    }
    (out / "tokens.json").write_text(json.dumps(tokens, indent=2))
    print(f"wrote {out}/signing.key, jwks.json, tokens.json for: {', '.join(IDENTITIES)}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gateway/jwt")
