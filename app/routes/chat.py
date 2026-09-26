from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Form, HTTPException, Request, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from app.db import get_db, query_one, init_db
from app.llm import build_context_block, compress_image_to_dataurl, stream_chat
from app.routes.auth import get_current_eleve

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

MAX_MESSAGE_CHARS = 4000
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/heic", "image/webp"}
MAX_IMAGE_BYTES = 12 * 1024 * 1024


def _get_exercice(slug: str):
    return query_one(
        """
        SELECT x.id, x.classe_id, x.slug, x.titre, x.enonce, x.correction,
               c.nom AS classe_nom, c.annee_scolaire
        FROM devoirsfaits.exercices x JOIN devoirsfaits.classes c ON c.id = x.classe_id
        WHERE x.slug = %s
        """,
        (slug,),
    )


def _get_or_create_conversation(db, eleve_id: int, exercice_id: int) -> int:
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


def _load_history(db, conversation_id: int) -> list[dict]:
    rows = db.execute(
        "SELECT role, content, (image IS NOT NULL) AS has_image "
        "FROM devoirsfaits.messages WHERE conversation_id = %s ORDER BY id",
        (conversation_id,),
    ).fetchall()
    return [
        {"role": r["role"], "content": r["content"], "has_image": r["has_image"]}
        for r in rows
    ]


def _save_message(
    db, conversation_id: int, role: str, content: str, image: bytes | None = None
) -> None:
    db.execute(
        "INSERT INTO devoirsfaits.messages (conversation_id, role, content, image) VALUES (%s, %s, %s, %s)",
        (conversation_id, role, content, image),
    )


def _sse_chunk(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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


@router.get("/api/chat/{slug}/history")
async def chat_history(request: Request, slug: str):
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    exercice = _get_exercice(slug)
    if not exercice:
        raise HTTPException(status_code=404, detail="Exercice inconnu")
    if exercice["classe_id"] != eleve["classe_id"]:
        raise HTTPException(status_code=403, detail="Exercice d'une autre classe")

    with get_db() as db:
        conv_id = _get_or_create_conversation(db, eleve["id"], exercice["id"])
        history = _load_history(db, conv_id)

    return JSONResponse({
        "exercice": {"titre": exercice["titre"], "slug": exercice["slug"]},
        "eleve": {"prenom": eleve["prenom"], "nom": eleve["nom"]},
        "messages": history,
    })


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
    if exercice["classe_id"] != eleve["classe_id"]:
        raise HTTPException(status_code=403, detail="Exercice d'une autre classe")

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
    if image_bytes:
        try:
            image_dataurl = compress_image_to_dataurl(image_bytes)
        except Exception:
            raise HTTPException(status_code=422, detail="Image illisible")
        import base64

        stored_image = base64.b64decode(image_dataurl.split(",", 1)[1])

    init_db()

    with get_db() as db:
        conv_id = _get_or_create_conversation(db, eleve["id"], exercice["id"])
        history = _load_history(db, conv_id)
        _save_message(
            db, conv_id, "user", message or "Voici une photo de mon cahier.", stored_image
        )

        eleve_dict = dict(eleve)
        ex_dict = dict(exercice)
        context_block = build_context_block(eleve_dict, ex_dict)

        session_id = f"conv-{conv_id}"
        user_id = f"eleve-{eleve['id']}-{eleve['login']}"
        tags = ["devoirsfaits", ex_dict["classe_nom"], exercice["slug"]]
        metadata = {
            "eleve": f"{eleve['prenom']} {eleve['nom']}",
            "classe": ex_dict["classe_nom"],
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
