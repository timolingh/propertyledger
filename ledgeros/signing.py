from __future__ import annotations

import base64
import hashlib
import hmac
from dataclasses import dataclass


@dataclass(frozen=True)
class SignedRequest:
    signature: str
    signing_payload: str


def canonical_request_payload(
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
    client_id: str,
) -> str:
    normalized_path = path if path.startswith("/") else f"/{path}"
    body_hash = hashlib.sha256(body).hexdigest()
    return "\n".join([method.upper(), normalized_path, timestamp, client_id, body_hash])


def sign_request(
    *,
    method: str,
    path: str,
    body: bytes,
    timestamp: str,
    client_id: str,
    secret: str,
) -> SignedRequest:
    payload = canonical_request_payload(method, path, body, timestamp, client_id)
    digest = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.b64encode(digest).decode("ascii")
    return SignedRequest(signature=signature, signing_payload=payload)
