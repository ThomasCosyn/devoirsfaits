from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db
from app.routes import auth, chat, sync


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(sync.router)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/sw.js")
async def service_worker():
    """Service worker servi à la racine (scope /) pour rendre l'app installable (PWA)."""
    content = (Path(__file__).parent / "static" / "sw.js").read_bytes()
    return Response(
        content=content,
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )
