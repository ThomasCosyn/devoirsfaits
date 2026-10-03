from __future__ import annotations

import hashlib
import json
import logging
import uuid

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.db import get_db, query_one, init_db
from app.llm import (
    build_context_block,
    compress_image_to_dataurl,
    stream_chat,
    transcribe_image,
)
from app.routes.auth import get_current_eleve

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_MESSAGE_CHARS = 4000
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024


LIBRE_SLUG = "libre"


def _get_exercice(slug: str):
    if slug == LIBRE_SLUG:
        return {
            "id": None,
            "niveau_id": None,
            "slug": LIBRE_SLUG,
            "titre": "Exercice libre",
            "enonce": "",
            "correction": "",
            "niveau_nom": None,
            "classe_nom": None,
            "annee_scolaire": None,
        }
    return query_one(
        """
        SELECT x.id, x.niveau_id, x.slug, x.titre, x.enonce, x.correction,
               n.nom AS niveau_nom
        FROM devoirsfaits.exercices x JOIN devoirsfaits.niveaux n ON n.id = x.niveau_id
        WHERE x.slug = %s
        """,
        (slug,),
    )


def _get_or_create_conversation(db, eleve_id: int, exercice_id: int | None) -> int:
    if exercice_id is not None:
        row = db.execute(
            "SELECT id FROM devoirsfaits.conversations WHERE eleve_id = %s AND exercice_id = %s",
            (eleve_id, exercice_id),
        ).fetchone()
        if row:
            return row["id"]
        cur = db.execute(
            "INSERT INTO devoirsfaits.conversations (eleve_id, exercice_id) VALUES (%s, %s) RETURNING id",
            (eleve_id, exercice_id),
        )
        return cur.fetchone()["id"]
    row = db.execute(
        "SELECT id FROM devoirsfaits.conversations "
        "WHERE eleve_id = %s AND exercice_id IS NULL ORDER BY id DESC LIMIT 1",
        (eleve_id,),
    ).fetchone()
    if row:
        return row["id"]
    cur = db.execute(
        "INSERT INTO devoirsfaits.conversations (eleve_id) VALUES (%s) RETURNING id",
        (eleve_id,),
    )
    return cur.fetchone()["id"]


def _load_history(db, conversation_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT id, role, content, (image IS NOT NULL) AS has_image, image_transcript "
        "FROM devoirsfaits.messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "role": r["role"],
            "content": r["content"],
            "has_image": r["has_image"],
            "image_transcript": r["image_transcript"],
        }
        for r in rows
    ]


def _save_message(
    db,
    conversation_id: int,
    role: str,
    content: str,
    image: bytes | None = None,
    image_transcript: str | None = None,
) -> None:
    db.execute(
        "INSERT INTO devoirsfaits.messages "
        "(conversation_id, role, content, image, image_transcript) "
        "VALUES (%s, %s, %s, %s, %s)",
        (conversation_id, role, content, image, image_transcript),
    )


def _sse_chunk(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.get("/e/libre", response_class=HTMLResponse)
async def exercice_libre_page(request: Request):
    eleve = get_current_eleve(request)
    if not eleve:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": "/e/libre", "error": None},
        )
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"eleve": dict(eleve), "exercice": {"titre": "Exercice libre", "slug": "libre", "enonce": ""}},
    )


@router.get("/", response_class=HTMLResponse)
async def home_page(request: Request):
    from fastapi.responses import RedirectResponse

    if get_current_eleve(request):
        return RedirectResponse("/e/libre", status_code=303)
    return templates.TemplateResponse(
        request,
        "login.html",
        {"next": "/e/libre", "error": None},
    )


@router.get("/e/{slug}", response_class=HTMLResponse)
async def exercice_page(request: Request, slug: str):
    eleve = get_current_eleve(request)
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    if not eleve:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": f"/e/{slug}", "error": None, "exercice_titre": exercice["titre"]},
        )
    return templates.TemplateResponse(
        request,
        "chat.html",
        {"eleve": dict(eleve), "exercice": dict(exercice)},
    )


@router.post("/api/chat/{slug}/reset")
async def chat_reset(request: Request, slug: str):
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    if exercice["niveau_id"] is not None and exercice["niveau_id"] != eleve["niveau_id"]:
        raise HTTPException(status_code=403, detail="Exercice d'un autre niveau")
    with get_db() as db:
        db.execute(
            """
            DELETE FROM devoirsfaits.messages
            WHERE conversation_id IN (
                SELECT id FROM devoirsfaits.conversations
                WHERE eleve_id = %s AND exercice_id IS NOT DISTINCT FROM %s
            )
            """,
            (eleve["id"], exercice["id"]),
        )
        db.execute(
            """
            DELETE FROM devoirsfaits.conversations
            WHERE eleve_id = %s AND exercice_id IS NOT DISTINCT FROM %s
            """,
            (eleve["id"], exercice["id"]),
        )
    return JSONResponse({"ok": True})


@router.get("/api/chat/{slug}/history")
async def chat_history(request: Request, slug: str):
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    if exercice["niveau_id"] is not None and exercice["niveau_id"] != eleve["niveau_id"]:
        raise HTTPException(status_code=403, detail="Exercice d'un autre niveau")

    with get_db() as db:
        conv_id = _get_or_create_conversation(db, eleve["id"], exercice["id"])
        history = _load_history(db, conv_id)

    return JSONResponse({
        "exercice": {"titre": exercice["titre"], "slug": exercice["slug"]},
        "eleve": {"prenom": eleve["prenom"], "nom": eleve["nom"]},
        "messages": history,
    })


@router.get("/api/chat/{slug}/image/{message_id}")
async def chat_image(request: Request, slug: str, message_id: int):
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    with get_db() as db:
        row = db.execute(
            """
            SELECT m.image FROM devoirsfaits.messages m
            JOIN devoirsfaits.conversations c ON c.id = m.conversation_id
            WHERE m.id = %s AND c.eleve_id = %s AND m.image IS NOT NULL
            """,
            (message_id, eleve["id"]),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Image introuvable")
    return Response(content=row["image"], media_type="image/jpeg")


@router.post("/api/chat/{slug}")
async def chat_endpoint(
    request: Request,
    slug: str,
    message: str = Form(""),
    image: UploadFile | None = File(None),
):
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    if exercice["niveau_id"] is not None and exercice["niveau_id"] != eleve["niveau_id"]:
        raise HTTPException(status_code=403, detail="Exercice d'un autre niveau")

    message = (message or "").strip()
    image_bytes: bytes | None = None
    if image is not None and image.filename:
        raw = await image.read()
        if len(raw) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image trop lourde (max 12 Mo)")
        if image.content_type not in ALLOWED_IMAGE_TYPES:
            raise HTTPException(status_code=415, detail="Format d'image non supporté")
        image_bytes = raw

    if not message and not image_bytes:
        raise HTTPException(status_code=422, detail="Message vide")

    if len(message) > MAX_MESSAGE_CHARS:
        message = message[:MAX_MESSAGE_CHARS]

    image_dataurl = None
    stored_image: bytes | None = None
    image_transcript = None
    if image_bytes:
        try:
            image_dataurl = compress_image_to_dataurl(image_bytes)
        except Exception:
            raise HTTPException(status_code=422, detail="Image illisible")
        import base64

        stored_image = base64.b64decode(image_dataurl.split(",", 1)[1])
        try:
            image_transcript = await transcribe_image(image_dataurl)
        except Exception:
            logging.getLogger("devoirsfaits").exception(
                "Transcription d'image échouée (modèle=%s)", settings.MISTRAL_MODEL
            )
            image_transcript = None
        if not image_transcript:
            image_transcript = "(Photo envoyée mais transcription indisponible.)"

    init_db()

    user_content = message or "Voici une photo de mon cahier."
    with get_db() as db:
        conv_id = _get_or_create_conversation(db, eleve["id"], exercice["id"])
        history = _load_history(db, conv_id)
        _save_message(
            db, conv_id, "user", user_content, stored_image, image_transcript
        )
        history.append(
            {
                "role": "user",
                "content": user_content,
                "has_image": image_dataurl is not None,
                "image_transcript": image_transcript,
            }
        )

        eleve_dict = dict(eleve)
        ex_dict = dict(exercice)
        context_block = build_context_block(eleve_dict, ex_dict)

        session_hash = hashlib.sha256(
            f"{eleve['login']}:{conv_id}".encode()
        ).hexdigest()[:12]
        session_id = f"conv-{session_hash}"
        user_id = eleve["login"]
        tags = ["devoirsfaits", ex_dict["niveau_nom"] or "libre", exercice["slug"]]
        metadata = {
            "eleve": f"{eleve['prenom']} {eleve['nom']}",
            "classe": eleve["classe_nom"],
            "niveau": ex_dict["niveau_nom"],
            "exercice": exercice["slug"],
            "titre_exercice": exercice["titre"],
            "conversation_id": conv_id,
            "avec_photo": image_dataurl is not None,
        }

    async def event_stream():
        full_reply = []
        try:
            async for token in stream_chat(
                history,
                context_block,
                session_id=session_id,
                user_id=user_id,
                tags=tags,
                metadata=metadata,
                image_dataurl=image_dataurl,
            ):
                full_reply.append(token)
                yield _sse_chunk({"type": "token", "content": token})
        except Exception:
            yield _sse_chunk({"type": "error", "content": "Erreur de l'assistant. Réessaie dans un instant."})
            return
        reply = "".join(full_reply)
        if reply:
            with get_db() as db:
                _save_message(db, conv_id, "assistant", reply)
        yield _sse_chunk({"type": "done", "content": reply})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
