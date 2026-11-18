"""Tuteur v2 : contrat de l'API POST /api/chat (stream de texte brut) et génération
des réponses de référence du catalogue d'exercices.

Contient uniquement de la logique testable sans base de données :
- construction des blocs de prompt injectés dynamiquement (référence, niveau d'indice),
- validation des blocs ```brouillon``` et relance/retrait,
- garde-fou anti-fuite de la réponse finale au niveau d'indice 0,
- prompt + validation de la génération en lot (CLI).
"""
from __future__ import annotations

import base64
import json
import logging
import re
from contextlib import nullcontext
from typing import Any, AsyncIterator, Callable

from pydantic import BaseModel, Field

from app.config import settings
from app.langfuse_ext import get_langfuse
from app.llm import SYSTEM_PROMPT, _cached_tokens, _extract_text, get_client, select_chapitres

logger = logging.getLogger("devoirsfaits")

# ---------------------------------------------------------------------------
# Modèles de la requête POST /api/chat
# ---------------------------------------------------------------------------


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatContextIn(BaseModel):
    exercice_id: str = ""
    niveau_indice: int = 0
    eleve: str = ""
    classe: str = ""


class ChatRequestIn(BaseModel):
    messages: list[ChatMessageIn] = Field(default_factory=list)
    image: str | None = None
    context: ChatContextIn = Field(default_factory=ChatContextIn)


MAX_HISTORY_MESSAGES = 40
MAX_MESSAGE_CHARS = 4000
MAX_IMAGE_BYTES = 12 * 1024 * 1024
ALLOWED_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp", "image/heic"}

DATAURL_RE = re.compile(r"^data:(image/[a-zA-Z0-9.+-]+);base64,([A-Za-z0-9+/=\s]+)$")


def clamp_indice(value: Any) -> int:
    try:
        return max(0, min(3, int(value)))
    except (TypeError, ValueError):
        return 0


def sanitize_history(messages: list[ChatMessageIn]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages[-MAX_HISTORY_MESSAGES:]:
        role = m.role if m.role in ("user", "assistant") else "user"
        content = (m.content or "")[:MAX_MESSAGE_CHARS].strip()
        out.append({"role": role, "content": content})
    return out


def parse_image_dataurl(dataurl: str | None) -> tuple[str | None, bytes | None]:
    """Valide une data URL base64 ; retourne (mime, octets) ou (None, None)."""
    if not dataurl:
        return None, None
    m = DATAURL_RE.match(dataurl.strip())
    if not m:
        return None, None
    mime, b64 = m.groups()
    if mime not in ALLOWED_IMAGE_MIMES:
        return None, None
    try:
        raw = base64.b64decode(re.sub(r"\s", "", b64), validate=True)
    except Exception:
        return None, None
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        return None, None
    return mime, raw


# ---------------------------------------------------------------------------
# Blocs de prompt injectés dynamiquement
# ---------------------------------------------------------------------------

TUTOR_RULES = r"""## Contrat de l'interface (à respecter strictement)

### Format des maths
LaTeX uniquement : `$...$` en ligne et `$$...$$` en bloc display. N'utilise JAMAIS `\(`, `\)`, `\[` ni `\]`.

### Balise d'étape
Au tout début de chacune de tes réponses, émets exactement une balise `<etape n="N" total="T"/>` :
- `N` = numéro de l'étape en cours (à partir de 1),
- `T` = nombre total d'étapes de l'exercice (`T` = len(étapes) de la réponse de référence ; s'il n'y a pas
  de référence structurée, choisis toi-même `T` entre 2 et 5 et reste cohérent ensuite).
Cette balise est masquée côté élève (elle pilote sa barre de progression) : ne la mentionne pas dans ton texte.

### Bloc brouillon
Au plus UN bloc par réponse, et seulement quand l'élève doit remplir quelque chose (calcul à trous,
tableau de signes ou de variations, lignes d'un algorithme). Jamais de bloc brouillon pour un exercice
de logique ou de démonstration. Format exact :
```brouillon
{"type":"lignes","lignes":[{"tex":"120 = 84 \\times 1 + 36","etat":"fait"},{"tex":"84 = 36 \\times [[a]] + [[b]]","etat":"a_faire"},{"tex":"36 = \\dots","etat":"verrouille"}]}
```
ou
```brouillon
{"type":"tableau","entetes":["x","-\\infty","-3","2","+\\infty"],"lignes":[{"cellules":["x+3","[[a]]","0","+","+"],"etat":"a_faire"}]}
```
Règles : JSON strictement valide (dans le bloc, les backslashes LaTeX sont doublés) ; une case à remplir
s'écrit `[[id]]` ; une seule ligne en `a_faire` à la fois (`fait` = déjà fait, `verrouille` = non modifiable) ;
ne mets JAMAIS la bonne valeur dans une case `[[...]]`.

### Messages « Mon brouillon : »
Quand l'élève envoie un message commençant par « Mon brouillon : », il y a recopié les valeurs de ses cases.
Compare-les une par une à la réponse de référence : félicite celles qui sont justes, et pour les fausses,
pose une question qui l'amène à corriger lui-même, sans donner la valeur.
"""

HINT_LEVELS = {
    0: "questions socratiques uniquement : pose des questions pour le faire réfléchir, aucune indication de méthode",
    1: "rappel de la notion de cours utile pour l'exercice",
    2: "indication de la méthode à utiliser (sans dérouler le calcul)",
    3: "première étape faite AVEC l'élève, sans donner le résultat final",
}


def parse_etapes(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if str(x).strip()]
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return []
    if isinstance(data, list):
        return [str(x) for x in data if str(x).strip()]
    return []


def build_reference_block(exercice: dict) -> str:
    ref = (exercice.get("reponse_finale") or "").strip()
    methode = (exercice.get("methode") or "").strip()
    etapes = parse_etapes(exercice.get("etapes"))
    statut = exercice.get("statut")
    correction = (exercice.get("correction") or "").strip()

    if statut == "brouillon":
        return (
            "## RÉPONSE DE RÉFÉRENCE\n"
            "Aucune réponse de référence validée n'est disponible pour cet exercice (statut « brouillon »). "
            "Ne la considère PAS comme une vérité : reste prudent sur la validation, vérifie toi-même chaque "
            "calcul de l'élève étape par étape, et ne confirme un résultat que si tu l'as recalculé toi-même."
        )
    if not (ref or methode or etapes):
        if correction:
            return (
                "## CORRECTION DE RÉFÉRENCE (confidentielle — à ne donner qu'à la toute fin, "
                "parfaitement rédigée)\n" + correction
            )
        return (
            "## RÉPONSE DE RÉFÉRENCE\n"
            "Aucune réponse de référence n'est disponible pour cet exercice. Aide l'élève à construire "
            "la solution étape par étape, puis fais-lui rédiger la correction complète à la fin."
        )

    lines = ["## RÉPONSE DE RÉFÉRENCE (confidentielle — ne JAMAIS la donner spontanément)"]
    if ref:
        lines.append(f"- Réponse finale : {ref}")
    if methode:
        lines.append(f"- Méthode en une ligne : {methode}")
    if etapes:
        lines.append("- Étapes de l'exercice :")
        lines += [f"  {i + 1}) {e}" for i, e in enumerate(etapes)]
    lines.append(
        "Si l'élève propose une réponse, compare-la à la réponse finale de référence et guide-le par des "
        "questions ; ne lui dis pas simplement « c'est bon » ou « c'est faux » sans l'amener à le voir lui-même."
    )
    return "\n".join(lines)


def build_hint_block(niveau_indice: int) -> str:
    n = clamp_indice(niveau_indice)
    return (
        f"## NIVEAU D'INDICE demandé par l'élève : {n}\n"
        f"{HINT_LEVELS[n]}\n"
        "Quel que soit le niveau, ne donne JAMAIS la réponse finale spontanément."
    )


def build_tutor_context(eleve: dict, exercice: dict, niveau_indice: int) -> str:
    programme_section = select_chapitres(
        eleve.get("programme", ""), exercice.get("chapitres"), exercice
    )
    parts = [
        "## Contexte de la session\n\n"
        "### Élève\n"
        f"- Prénom : {eleve['prenom']}\n"
        f"- Classe : {eleve.get('classe_nom')} ({eleve.get('niveau_nom')}, année {eleve.get('annee_scolaire')})\n\n"
        f"{programme_section}"
    ]
    if exercice.get("slug") == "libre" or not exercice.get("enonce"):
        parts.append(
            "### Mode exercice libre\n"
            "L'élève n'est pas venu depuis une feuille d'exercices : attends qu'il envoie son énoncé "
            "(texte ou photo), ou demande-le-lui. Il n'y a pas de réponse de référence : applique la méthode "
            "socratique, puis fais-lui rédiger la correction complète à la fin."
        )
    else:
        parts.append(
            "### Exercice sur lequel il est bloqué\n"
            f"- Titre : {exercice['titre']}\n"
            f"- Énoncé :\n{exercice['enonce']}"
        )
        parts.append(build_reference_block(exercice))
    parts.append(build_hint_block(niveau_indice))
    return "\n\n".join(parts)


def build_tutor_api_messages(
    history: list[dict[str, str]],
    eleve: dict,
    exercice: dict,
    niveau_indice: int,
    image_dataurl: str | None = None,
) -> list[dict[str, Any]]:
    system = SYSTEM_PROMPT + "\n\n" + TUTOR_RULES + "\n\n" + build_tutor_context(eleve, exercice, niveau_indice)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages += [{"role": m["role"], "content": m["content"]} for m in history]
    if image_dataurl and messages and messages[-1]["role"] == "user":
        text = messages[-1]["content"] or "Voici une photo de mon cahier."
        messages[-1]["content"] = [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": image_dataurl}},
        ]
    return messages


# ---------------------------------------------------------------------------
# Blocs brouillon : extraction, validation, réparation
# ---------------------------------------------------------------------------

BROUILLON_RE = re.compile(r"```brouillon[ \t]*\n([\s\S]*?)```")
ETAPE_RE = re.compile(r'<etape\s+n="(\d+)"\s+total="(\d+)"\s*/?>')
BROUILLON_ETATS = ("fait", "a_faire", "verrouille")


def validate_brouillon_payload(payload: str) -> list[str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as e:
        return [f"JSON invalide ({e.msg})"]
    if not isinstance(data, dict):
        return ["le bloc doit être un objet JSON"]
    t = data.get("type")
    errors: list[str] = []
    if t == "lignes":
        lignes = data.get("lignes")
        if not isinstance(lignes, list) or not lignes:
            return ["'lignes' doit être une liste non vide"]
        a_faire = 0
        for i, l in enumerate(lignes):
            if not isinstance(l, dict) or not isinstance(l.get("tex"), str):
                errors.append(f"lignes[{i}]: 'tex' manquant ou non textuel")
                continue
            etat = l.get("etat")
            if etat not in BROUILLON_ETATS:
                errors.append(f"lignes[{i}]: etat {etat!r} inconnu (fait|a_faire|verrouille)")
            elif etat == "a_faire":
                a_faire += 1
        if a_faire > 1:
            errors.append(f"{a_faire} lignes 'a_faire' (une seule à la fois)")
    elif t == "tableau":
        entetes = data.get("entetes")
        lignes = data.get("lignes")
        if not isinstance(entetes, list) or not entetes or not all(isinstance(h, str) for h in entetes):
            errors.append("'entetes' doit être une liste non vide de chaînes")
        if not isinstance(lignes, list) or not lignes:
            errors.append("'lignes' doit être une liste non vide")
        else:
            a_faire = 0
            for i, l in enumerate(lignes):
                if not isinstance(l, dict) or not isinstance(l.get("cellules"), list):
                    errors.append(f"lignes[{i}]: 'cellules' manquantes ou non liste")
                    continue
                etat = l.get("etat")
                if etat not in BROUILLON_ETATS:
                    errors.append(f"lignes[{i}]: etat {etat!r} inconnu (fait|a_faire|verrouille)")
                elif etat == "a_faire":
                    a_faire += 1
            if a_faire > 1:
                errors.append(f"{a_faire} lignes 'a_faire' (une seule à la fois)")
    else:
        errors.append(f"type {t!r} inconnu (attendu : lignes|tableau)")
    return errors


def brouillon_errors(text: str) -> list[str]:
    errors: list[str] = []
    for k, m in enumerate(BROUILLON_RE.finditer(text), start=1):
        for err in validate_brouillon_payload(m.group(1)):
            errors.append(f"bloc brouillon #{k}: {err}")
    return errors


def strip_invalid_brouillon(text: str) -> str:
    def repl(m: re.Match) -> str:
        return "" if validate_brouillon_payload(m.group(1)) else m.group(0)

    return BROUILLON_RE.sub(repl, text)


# ---------------------------------------------------------------------------
# Garde-fou anti-fuite de la réponse de référence (niveau d'indice 0)
# ---------------------------------------------------------------------------

REDACTED = "[réponse de référence masquée]"


def _normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower()


def contains_reference(text: str, reponse_finale: str) -> bool:
    ref = _normalize(reponse_finale or "")
    return bool(ref) and len(ref) >= 3 and ref in _normalize(text)


def redact_reference(text: str, reponse_finale: str) -> str:
    out = text
    for variant in {reponse_finale, reponse_finale.strip()}:
        if variant:
            out = out.replace(variant, REDACTED)
    return out


# ---------------------------------------------------------------------------
# Génération de la réponse avec validation + relance
# ---------------------------------------------------------------------------

StreamFn = Callable[[list[dict[str, Any]]], AsyncIterator[str]]

_FIX_PROMPT = (
    "Ton message précédent contient des erreurs de format : {problems}. "
    "Regénère ta réponse en corrigeant strictement ces points : bloc ```brouillon en JSON valide "
    "(backslashs LaTeX doublés, type lignes|tableau, une seule ligne a_faire, cases [[id]]), "
    "balise <etape n=\"N\" total=\"T\"/> au début de la réponse, et jamais la réponse finale de "
    "référence à ce stade de l'exercice."
)


async def _collect(stream_fn: StreamFn, messages: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    async for chunk in stream_fn(messages):
        parts.append(chunk)
    return "".join(parts)


async def generate_reply(
    api_messages: list[dict[str, Any]],
    *,
    stream_fn: StreamFn,
    reponse_finale: str | None = None,
    niveau_indice: int = 0,
    max_retries: int = 2,
) -> str:
    """Génère la réponse complète, valide les blocs brouillon, relance en cas d'erreur,
    puis retire/masque ce qui reste invalide (brouillon) ou interdit (fuite de la
    réponse finale au niveau d'indice 0)."""
    reply = await _collect(stream_fn, api_messages)
    for _ in range(max_retries):
        problems = brouillon_errors(reply)
        if niveau_indice == 0 and reponse_finale and contains_reference(reply, reponse_finale):
            problems.append(
                "la réponse contient la réponse finale de référence, qu'il ne faut jamais révéler "
                "à ce niveau d'indice"
            )
        if not problems:
            return reply
        fix = _FIX_PROMPT.format(problems="; ".join(problems))
        api_messages = [
            *api_messages,
            {"role": "assistant", "content": reply},
            {"role": "user", "content": fix},
        ]
        reply = await _collect(stream_fn, api_messages)
    reply = strip_invalid_brouillon(reply)
    if niveau_indice == 0 and reponse_finale and contains_reference(reply, reponse_finale):
        reply = redact_reference(reply, reponse_finale)
    return reply


# ---------------------------------------------------------------------------
# Fonction de streaming LLM (entrée Langfuse réduite : jamais de contenu en clair)
# ---------------------------------------------------------------------------


def _redacted_input(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in messages:
        content = m.get("content")
        if isinstance(content, str):
            length = len(content)
        elif isinstance(content, list):
            length = sum(len(p.get("text", "")) for p in content if isinstance(p, dict))
        else:
            length = 0
        out.append({"role": m.get("role"), "content_length": length})
    return out


def make_stream_fn(
    *, session_id: str, user_id: str, tags: list[str], metadata: dict[str, Any]
) -> StreamFn:
    """Fabrique une fonction de streaming ; les traces Langfuse ne contiennent que des
    métadonnées (rôles, tailles, usage) — jamais le contenu des messages."""

    async def stream_fn(messages: list[dict[str, Any]]) -> AsyncIterator[str]:
        client = get_client()
        lf = get_langfuse()
        if lf is not None:
            from langfuse import propagate_attributes

            attr_ctx = propagate_attributes(
                user_id=user_id,
                session_id=session_id,
                tags=tags,
                metadata=metadata,
                trace_name=f"chat-{metadata.get('exercice', 'ex')}",
            )
        else:
            attr_ctx = nullcontext()

        with attr_ctx:
            generation = None
            if lf is not None:
                generation = lf.start_observation(
                    name="chat-completion",
                    as_type="generation",
                    input=_redacted_input(messages),
                    model=settings.MISTRAL_MODEL,
                    model_parameters={
                        "max_tokens": settings.MISTRAL_MAX_TOKENS,
                        "temperature": 0.3,
                    },
                )
            collected: list[str] = []
            usage_details: dict[str, int] = {}
            try:
                stream = await client.chat.completions.create(
                    model=settings.MISTRAL_MODEL,
                    messages=messages,
                    max_tokens=settings.MISTRAL_MAX_TOKENS,
                    temperature=0.3,
                    stream=True,
                    stream_options={"include_usage": True},
                )
                async for chunk in stream:
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        usage_details = {
                            "input": getattr(usage, "prompt_tokens", 0) or 0,
                            "input_cached": _cached_tokens(usage),
                            "output": getattr(usage, "completion_tokens", 0) or 0,
                        }
                        logger.info(
                            "usage model=%s prompt=%d cached=%d completion=%d session=%s exercice=%s",
                            settings.MISTRAL_MODEL,
                            usage_details["input"],
                            usage_details["input_cached"],
                            usage_details["output"],
                            session_id,
                            metadata.get("exercice", "?"),
                        )
                    if not chunk.choices:
                        continue
                    content = _extract_text(getattr(chunk.choices[0].delta, "content", None))
                    if content:
                        collected.append(content)
                        yield content
            except Exception:
                if generation is not None:
                    generation.update(
                        output="".join(collected) and "[contenu non journalisé]",
                        level="ERROR",
                        status_message="échec du streaming de la complétion",
                    )
                    generation.end()
                raise
            if generation is not None:
                generation.update(
                    output="[contenu non journalisé]",
                    usage_details=usage_details or None,
                )
                generation.end()

    return stream_fn


# ---------------------------------------------------------------------------
# Génération en lot des réponses de référence (CLI enseignant)
# ---------------------------------------------------------------------------

GENERATION_SYSTEM_PROMPT = (
    "Tu es un professeur de mathématiques expérimenté qui prépare des fiches de référence "
    "pour un tuteur socratique. Tu réponds UNIQUEMENT avec un objet JSON strictement valide : "
    "aucun texte avant ou après, aucune balise ```."
)


def build_generation_messages(exercice: dict) -> list[dict[str, str]]:
    user = (
        f"Niveau : {exercice.get('niveau_nom') or '?'}\n"
        f"Titre : {exercice.get('titre') or ''}\n"
        f"Énoncé :\n{exercice.get('enonce') or ''}\n"
    )
    if exercice.get("correction"):
        user += f"\nCorrigé de l'enseignant (référence) :\n{exercice['correction']}\n"
    user += (
        "\nProduis un JSON strictement valide avec EXACTEMENT ces champs :\n"
        "{\n"
        '  "reponse_finale": "réponse finale exacte, en texte/LaTeX ($...$)",\n'
        '  "methode": "la méthode en une seule ligne",\n'
        '  "etapes": ["titre court de l\'étape 1", "..."],  // liste de 2 à 5 titres courts (une ligne chacun)\n'
        '  "statut": "brouillon"\n'
        "}\n"
        "La réponse finale doit être exacte et vérifiée. Les étapes doivent décomposer la résolution "
        "de façon socratique (petites étapes réalisables seules par l'élève)."
    )
    return [
        {"role": "system", "content": GENERATION_SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def validate_generation_payload(obj: Any) -> list[str]:
    if not isinstance(obj, dict):
        return ["la payload racine doit être un objet JSON"]
    errors: list[str] = []
    ref = obj.get("reponse_finale")
    methode = obj.get("methode")
    etapes = obj.get("etapes")
    if not isinstance(ref, str) or not ref.strip():
        errors.append("reponse_finale vide ou non textuelle")
    if not isinstance(methode, str) or not methode.strip():
        errors.append("methode vide ou non textuelle")
    if (
        not isinstance(etapes, list)
        or not 2 <= len(etapes) <= 5
        or not all(isinstance(e, str) and e.strip() and len(e) <= 120 for e in etapes)
    ):
        errors.append("etapes doit être une liste de 2 à 5 titres courts (<= 120 caractères chacun)")
    if obj.get("statut") != "brouillon":
        errors.append("statut doit être 'brouillon' (validation humaine requise avant import)")
    return errors


def normalize_generation_payload(obj: dict) -> dict[str, str]:
    return {
        "reponse_finale": obj["reponse_finale"].strip(),
        "methode": obj["methode"].strip(),
        "etapes": json.dumps([e.strip() for e in obj["etapes"]], ensure_ascii=False),
    }
