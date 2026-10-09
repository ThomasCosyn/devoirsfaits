from __future__ import annotations

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

BASE_DIR = Path(__file__).resolve().parent.parent

if load_dotenv is not None:
    load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


class Settings:
    BASE_DIR = BASE_DIR

    APP_NAME: str = "exo"
    SECRET_KEY: str = _env("SECRET_KEY", "dev-secret-change-me")
    DATABASE_URL: str = _env(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/postgres",
    )

    MISTRAL_API_KEY: str = _env("MISTRAL_API_KEY", "")
    MISTRAL_BASE_URL: str = _env(
        "MISTRAL_BASE_URL", "https://api.mistral.ai/v1")
    MISTRAL_MODEL: str = _env("MISTRAL_MODEL", "mistral-large-4")
    MISTRAL_MAX_TOKENS: int = int(_env("MISTRAL_MAX_TOKENS", "1500"))

    LANGFUSE_PUBLIC_KEY: str = _env("LANGFUSE_PUBLIC_KEY", "")
    LANGFUSE_SECRET_KEY: str = _env("LANGFUSE_SECRET_KEY", "")
    LANGFUSE_HOST: str = _env("LANGFUSE_HOST", "https://cloud.langfuse.com")

    IMAGE_MAX_DIM: int = int(_env("IMAGE_MAX_DIM", "1280"))
    IMAGE_JPEG_QUALITY: int = int(_env("IMAGE_JPEG_QUALITY", "70"))

    @property
    def langfuse_enabled(self) -> bool:
        return bool(self.LANGFUSE_PUBLIC_KEY and self.LANGFUSE_SECRET_KEY)


settings = Settings()
