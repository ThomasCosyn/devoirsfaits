"""Synchronisation des exercices depuis des fichiers .tex (feuille + corrigé).

Logique partagée entre :
- la CLI locale `python cli/manage.py sync ...` (accès direct à la base), et
- l'endpoint HTTP `POST /api/sync` (compte prof), exécuté dans le conteneur
  déployé, qui est le seul à joindre la base en private network.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from cli.latex_extract import (  # noqa: E402
    extract_askme,
    extract_askmecorrection,
    extract_exo_opt,
)

from app.db import get_db, query_one  # noqa: E402

DEFAULT_EXO_ENVS = ("exo", "exercice", "Exo")

# \askmeniveau{2de} dans le .tex : niveau par défaut si --niveau absent.
_ASKMENIVEAU_RE = re.compile(r"\\askmeniveau\{([^}]*)\}")


def _resolve_niveau_id(nom: str | None) -> int | None:
    if not nom:
        return None
    return (query_one("SELECT id FROM devoirsfaits.niveaux WHERE nom = %s", (nom,)) or {}).get("id")


def sync_tex_files(
    fichiers: list[tuple[str, str]],
    niveau: str | None = None,
    exo_envs: tuple[str, ...] = DEFAULT_EXO_ENVS,
) -> dict:
    """fichiers : liste (nom de fichier, contenu utf-8). Retourne un récapitulatif."""
    if not niveau:
        for _nom, content in fichiers:
            m = _ASKMENIVEAU_RE.search(content)
            if m:
                niveau = m.group(1).strip()
                break

    exercices: dict[str, dict] = {}
    corrections: dict[str, str] = {}
    for _nom, content in fichiers:
        exos = extract_askme(content)
        exos += extract_exo_opt(content, env_names=exo_envs)
        cors = extract_askmecorrection(content)
        for exo in exos:
            if exo["slug"] in exercices:
                continue
            if not exo.get("niveau") and niveau:
                exo["niveau"] = niveau
            exercices[exo["slug"]] = exo
        corrections.update(cors)

    if not exercices and not corrections:
        return {
            "created": 0,
            "updated": 0,
            "ignored": [],
            "error": (
                "Aucun exercice trouvé. Vérifiez que vos exercices utilisent "
                "\\begin{exo}[slug] ou \\begin{askme}{slug}{titre}{niveau}."
            ),
        }

    created, updated = 0, 0
    ignored: list[str] = []
    with get_db() as db:
        for slug, exo in exercices.items():
            niveau_id = _resolve_niveau_id(exo.get("niveau"))
            if not niveau_id:
                ignored.append(
                    f"{slug} (niveau {exo.get('niveau') or 'manquant'} inconnu — "
                    "créez-le d'abord avec add-niveau)"
                )
                continue
            existing = query_one(
                "SELECT id, correction FROM devoirsfaits.exercices WHERE slug = %s", (slug,)
            )
            # Sans corrigé fourni pour ce slug, on conserve la correction existante.
            correction = corrections.get(slug) or (existing["correction"] if existing else "")
            if existing:
                db.execute(
                    "UPDATE devoirsfaits.exercices SET niveau_id = %s, titre = %s, "
                    "enonce = %s, correction = %s WHERE id = %s",
                    (niveau_id, exo["titre"], exo["enonce"], correction, existing["id"]),
                )
                updated += 1
            else:
                db.execute(
                    "INSERT INTO devoirsfaits.exercices (niveau_id, slug, titre, enonce, correction) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (niveau_id, slug, exo["titre"], exo["enonce"], correction),
                )
                created += 1
        for slug, correction in corrections.items():
            if slug not in exercices:
                existing = query_one(
                    "SELECT id, correction FROM devoirsfaits.exercices WHERE slug = %s", (slug,)
                )
                if existing and not existing["correction"]:
                    db.execute(
                        "UPDATE devoirsfaits.exercices SET correction = %s WHERE id = %s",
                        (correction, existing["id"]),
                    )
    return {"created": created, "updated": updated, "ignored": ignored}
