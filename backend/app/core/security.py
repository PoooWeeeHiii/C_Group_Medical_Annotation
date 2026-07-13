from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.app.core.config import JWT_EXPIRE_HOURS, JWT_SECRET


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str, salt: str | None = None) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_value.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt_value}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, salt, digest = password_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000).hex()
    return hmac.compare_digest(candidate, digest)


def create_access_token(payload: dict[str, Any], expire_hours: int | None = None) -> str:
    hours = JWT_EXPIRE_HOURS if expire_hours is None else expire_hours
    body = {
        **payload,
        "exp": int((datetime.now(timezone.utc) + timedelta(hours=max(1, hours))).timestamp()),
    }
    encoded = _b64encode(json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
    signature = _b64encode(hmac.new(JWT_SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).digest())
    return f"{encoded}.{signature}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        encoded, signature = token.split(".", 1)
    except ValueError as exc:
        raise ValueError("Invalid token format") from exc
    expected = _b64encode(hmac.new(JWT_SECRET.encode("utf-8"), encoded.encode("utf-8"), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Invalid token signature")
    payload = json.loads(_b64decode(encoded).decode("utf-8"))
    if int(payload.get("exp") or 0) < int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("Token expired")
    return payload
