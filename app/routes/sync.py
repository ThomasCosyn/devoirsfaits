from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from app.routes.auth import get_current_eleve
from app.sync import DEFAULT_EXO_ENVS, sync_tex_files

router = APIRouter()

MAX_TEX_BYTES = 5 * 1024 * 1024


@router.post("/api/sync")
async def sync_endpoint(
    request: Request,
    fichiers: list[UploadFile] = File(...),
    niveau: str = Form(""),
    exo_env: list[str] = Form([]),
):
    """Upload de fichiers .tex (feuille + corrigé) — réservé aux comptes prof.

    Permet de synchroniser les exercices sans accès direct à la base depuis le
    poste enseignant : le conteneur déployé joint la base en private network.
    """
    eleve = get_current_eleve(request)
    if not eleve:
        raise HTTPException(status_code=401, detail="Non authentifié")
    if not eleve.get("est_prof"):
        raise HTTPException(status_code=403, detail="Réservé aux comptes enseignants")
    if not fichiers:
        raise HTTPException(status_code=422, detail="Aucun fichier .tex envoyé")
    contents: list[tuple[str, str]] = []
    for f in fichiers:
        raw = await f.read()
        if len(raw) > MAX_TEX_BYTES:
            raise HTTPException(status_code=413, detail=f"{f.filename} trop gros (max 5 Mo)")
        try:
            contents.append((f.filename or "feuille.tex", raw.decode("utf-8")))
        except UnicodeDecodeError:
            raise HTTPException(status_code=422, detail=f"{f.filename} n'est pas de l'UTF-8")
    result = sync_tex_files(
        contents,
        niveau=niveau.strip() or None,
        exo_envs=tuple(exo_env) or DEFAULT_EXO_ENVS,
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return JSONResponse(result)
