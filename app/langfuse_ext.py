from __future__ import annotations

from langfuse import Langfuse as _Langfuse

from app.config import settings

_client: _Langfuse | None = None


def get_langfuse() -> _Langfuse | None:
    global _client
    if not settings.langfuse_enabled:
        return None
    if _client is None:
        _client = _Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
    return _client
