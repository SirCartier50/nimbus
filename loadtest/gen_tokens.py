"""Mint load-test identities: an RSA keypair, a JWKS document, and N signed JWTs.

The backend verifies Clerk JWTs against {CLERK_ISSUER}/.well-known/jwks.json.
Pointing CLERK_ISSUER at a local static server that hosts OUR jwks.json means we
can sign as many valid tokens as we want — real code path (RS256, issuer check,
JWKS fetch), zero Clerk involvement, and each token gets its own `sub` so the
per-user rate limiter and DB rows behave exactly as in production.

Writes to ./out: .well-known/jwks.json and tokens.txt (one JWT per line).
"""
import base64
import json
import os
import time

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

N_USERS = int(os.getenv("N_USERS", "50"))
ISSUER = os.getenv("ISSUER", "http://jwks:8080")
OUT = os.path.join(os.path.dirname(__file__), "out")


def _b64url_uint(n: int) -> str:
    raw = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def main():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()

    os.makedirs(os.path.join(OUT, ".well-known"), exist_ok=True)
    jwks = {
        "keys": [
            {
                "kty": "RSA", "use": "sig", "alg": "RS256", "kid": "loadtest-key",
                "n": _b64url_uint(pub.n), "e": _b64url_uint(pub.e),
            }
        ]
    }
    with open(os.path.join(OUT, ".well-known", "jwks.json"), "w") as f:
        json.dump(jwks, f)

    now = int(time.time())
    with open(os.path.join(OUT, "tokens.txt"), "w") as f:
        for i in range(N_USERS):
            token = jwt.encode(
                {
                    "sub": f"loadtest-user-{i}",
                    "iss": ISSUER,
                    "iat": now,
                    "exp": now + 24 * 3600,
                },
                key,
                algorithm="RS256",
                headers={"kid": "loadtest-key"},
            )
            f.write(token + "\n")

    print(f"wrote jwks.json + {N_USERS} tokens (issuer {ISSUER}) to {OUT}")


if __name__ == "__main__":
    main()
