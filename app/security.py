from __future__ import annotations

import hashlib
import hmac
import json
import time

from fastapi import Request
from itsdangerous import URLSafeSerializer, BadSignature

from app.config import settings

_serializer = URLSafeSerializer(settings.SECRET_KEY, salt="devoirsfaits.session")
COOKIE_NAME = "df_session"
SESSION_TTL = 12 * 3600


def hash_password(password: str) -> str:
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt

    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_session_token(eleve_id: int) -> str:
    payload = {"eleve_id": eleve_id, "exp": int(time.time()) + SESSION_TTL}
    return _serializer.dumps(payload)


def read_session_token(token: str) -> int | None:
    try:
        payload = _serializer.loads(token)
    except BadSignature:
        return None
    if not isinstance(payload, dict) or payload.get("exp", 0) < time.time():
        return None
    eleve_id = payload.get("eleve_id")
    return eleve_id if isinstance(eleve_id, int) else None


def set_session_cookie(request: Request, response, eleve_id: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        create_session_token(eleve_id),
        max_age=SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(COOKIE_NAME)
