#!/usr/bin/env python3
"""A minimal OpenID Connect provider for local end-to-end tests. NEVER deploy this.

It auto-approves every authorization request as one configured user and signs real
RS256 ID tokens, so the API's full sign-in path (discovery, PKCE, code exchange,
signature/nonce/audience checks, session cookie) runs unmodified.

    FAKE_IDP_EMAIL=helena.voss@harbourchambers.int python scripts/fake_idp.py --port 8012
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwk, jwt

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PEM = KEY.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
PUBLIC = jwk.construct(
    KEY.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo), "RS256"
).to_dict() | {"kid": "fake-1", "use": "sig", "alg": "RS256"}
CODES: dict[str, dict] = {}


class Handler(BaseHTTPRequestHandler):
    issuer = ""

    def log_message(self, *_):  # quiet
        pass

    def _json(self, body: dict, status: int = 200) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        if url.path == "/.well-known/openid-configuration":
            return self._json({
                "issuer": self.issuer,
                "authorization_endpoint": f"{self.issuer}/authorize",
                "token_endpoint": f"{self.issuer}/token",
                "jwks_uri": f"{self.issuer}/jwks",
            })
        if url.path == "/jwks":
            return self._json({"keys": [PUBLIC]})
        if url.path == "/authorize":
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            code = secrets.token_urlsafe(16)
            CODES[code] = {"nonce": q["nonce"], "challenge": q["code_challenge"], "client_id": q["client_id"]}
            self.send_response(302)
            self.send_header("Location", f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q['state']})}")
            self.end_headers()
            return None
        return self._json({"error": "not found"}, 404)

    def do_POST(self):  # noqa: N802
        if urlparse(self.path).path != "/token":
            return self._json({"error": "not found"}, 404)
        form = {k: v[0] for k, v in parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode()).items()}
        grant = CODES.pop(form.get("code", ""), None)
        verifier_hash = base64.urlsafe_b64encode(hashlib.sha256(form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
        if grant is None or verifier_hash != grant["challenge"]:
            return self._json({"error": "invalid_grant"}, 400)
        now = int(time.time())
        claims = {
            "iss": self.issuer, "aud": grant["client_id"], "sub": "fake-user",
            "email": os.environ.get("FAKE_IDP_EMAIL", "helena.voss@harbourchambers.int"),
            "email_verified": True, "nonce": grant["nonce"], "iat": now, "exp": now + 300,
        }
        return self._json({"id_token": jwt.encode(claims, PEM, algorithm="RS256", headers={"kid": "fake-1"}),
                           "token_type": "Bearer", "access_token": "unused"})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8012)
    args = parser.parse_args()
    Handler.issuer = f"http://127.0.0.1:{args.port}"
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
