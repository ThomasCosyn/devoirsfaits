"""Tests du tuteur v2 (app/tutor.py) : blocs brouillon, balise <etape>,
garde-fou anti-fuite de la réponse finale au niveau d'indice 0, génération CLI."""
from __future__ import annotations

import asyncio
import json

from app import tutor

MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "Je bloque"}]


def make_stream_fn(replies):
    """stream_fn factice : renvoie les réponses fournies, une par appel."""
    calls = {"n": 0, "messages": []}

    async def stream_fn(messages):
        calls["messages"].append(messages)
        reply = replies[min(calls["n"], len(replies) - 1)]
        calls["n"] += 1
        yield reply

    return stream_fn, calls


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- balise etape


def test_balise_etape_preservee_sans_retry():
    reply = '<etape n="2" total="4"/>\nBien, passons à la suite : que vaut $x$ ?'
    stream_fn, calls = make_stream_fn([reply])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn))
    assert out == reply
    assert calls["n"] == 1
    m = tutor.ETAPE_RE.search(out)
    assert m and m.group(1) == "2" and m.group(2) == "4"


# ---------------------------------------------------------------- brouillon


def test_brouillon_lignes_valide():
    payload = json.dumps({
        "type": "lignes",
        "lignes": [
            {"tex": "120 = 84 \\times 1 + 36", "etat": "fait"},
            {"tex": "84 = 36 \\times [[a]] + [[b]]", "etat": "a_faire"},
            {"tex": "36 = \\dots", "etat": "verrouille"},
        ],
    })
    text = f'<etape n="1" total="3"/>\nVoici le calcul :\n```brouillon\n{payload}\n```'
    assert tutor.brouillon_errors(text) == []
    stream_fn, calls = make_stream_fn([text])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn))
    assert "```brouillon" in out
    assert calls["n"] == 1


def test_brouillon_tableau_valide():
    payload = json.dumps({
        "type": "tableau",
        "entetes": ["x", "-\\infty", "-3", "2", "+\\infty"],
        "lignes": [{"cellules": ["x+3", "[[a]]", "0", "+", "+"], "etat": "a_faire"}],
    })
    text = f"```brouillon\n{payload}\n```"
    assert tutor.brouillon_errors(text) == []


def test_brouillon_json_invalide_retry_puis_reponse_propre():
    bad = '<etape n="1" total="2"/>\n```brouillon\n{"type":"lignes","lignes": [\n```'
    good = '<etape n="1" total="2"/>\nPas de brouillon finalement, réfléchis.'
    stream_fn, calls = make_stream_fn([bad, good])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn))
    assert calls["n"] == 2
    assert out == good
    # le message de relance contient l'erreur constatée
    assert any(m["role"] == "user" and "JSON invalide" in m["content"] for m in calls["messages"][1])


def test_brouillon_invalide_retry_echoue_on_retire_le_bloc():
    bad = 'Texte avant.\n```brouillon\n{"type":"inconnu"}\n```\nTexte après.'
    stream_fn, calls = make_stream_fn([bad, bad])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn, max_retries=1))
    assert calls["n"] == 2
    assert "brouillon" not in out
    assert "Texte avant." in out and "Texte après." in out


def test_brouillon_plusieurs_a_faire_invalide():
    payload = json.dumps({
        "type": "lignes",
        "lignes": [
            {"tex": "a = [[x]]", "etat": "a_faire"},
            {"tex": "b = [[y]]", "etat": "a_faire"},
        ],
    })
    errors = tutor.brouillon_errors(f"```brouillon\n{payload}\n```")
    assert any("a_faire" in e for e in errors)


def test_brouillon_etat_inconnu_invalide():
    payload = json.dumps({"type": "lignes", "lignes": [{"tex": "a", "etat": "fait_tellement"}]})
    errors = tutor.brouillon_errors(f"```brouillon\n{payload}\n```")
    assert any("etat" in e for e in errors)


# ------------------------------------------------------- anti-fuite référence

REF = "PGCD(120, 84) = 12"


def test_aucune_fuite_reponse_finale_niveau0_avec_retry():
    leak = f'<etape n="1" total="3"/>\nLa réponse est {REF}.'
    clean = '<etape n="1" total="3"/>\nQuel est le plus grand diviseur commun de 120 et 84 ?'
    stream_fn, calls = make_stream_fn([leak, clean])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn, reponse_finale=REF, niveau_indice=0))
    assert REF not in out
    assert calls["n"] == 2


def test_fuite_niveau0_redaction_si_retry_echoue():
    leak = f'<etape n="1" total="3"/>\nLa réponse est {REF}.'
    stream_fn, _ = make_stream_fn([leak, leak])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn, reponse_finale=REF, niveau_indice=0, max_retries=1))
    assert REF not in out
    assert tutor.REDACTED in out


def test_pas_de_redaction_aux_autres_niveaux():
    reply = f'<etape n="3" total="3"/>\nOn aboutit bien à {REF} à la fin.'
    stream_fn, calls = make_stream_fn([reply])
    out = run(tutor.generate_reply(MSGS, stream_fn=stream_fn, reponse_finale=REF, niveau_indice=3))
    assert calls["n"] == 1
    assert REF in out


# ------------------------------------------------------------- blocs de prompt


def test_bloc_reference_valide_contient_champs():
    exo = {
        "statut": "valide",
        "reponse_finale": "$12$",
        "methode": "algorithme d'Euclide",
        "etapes": json.dumps(["Décomposer 120", "Décomposer 84", "Commun"]),
        "correction": "corr",
    }
    block = tutor.build_reference_block(exo)
    assert "$12$" in block
    assert "algorithme d'Euclide" in block
    assert "1) Décomposer 120" in block and "3) Commun" in block
    assert "confidentielle" in block.lower()


def test_bloc_reference_brouillon_ne_divulgue_rien():
    exo = {
        "statut": "brouillon",
        "reponse_finale": "$12$",
        "methode": "algorithme d'Euclide",
        "etapes": json.dumps(["a", "b"]),
        "correction": "",
    }
    block = tutor.build_reference_block(exo)
    assert "$12$" not in block
    assert "Euclide" not in block
    assert "brouillon" in block.lower()
    assert "prudent" in block.lower()


def test_bloc_reference_legacy_correction():
    exo = {"statut": "valide", "reponse_finale": None, "methode": None, "etapes": None, "correction": "La correction du prof."}
    block = tutor.build_reference_block(exo)
    assert "La correction du prof." in block


def test_bloc_indice_niveaux():
    for n in range(4):
        block = tutor.build_hint_block(n)
        assert f"NIVEAU D'INDICE" in block and f": {n}" in block
    assert "socratique" in tutor.build_hint_block(0).lower()
    assert tutor.clamp_indice(99) == 3
    assert tutor.clamp_indice(-2) == 0
    assert tutor.clamp_indice("abc") == 0


def test_api_messages_structure_et_image():
    eleve = {"prenom": "Léa", "classe_nom": "3A", "niveau_nom": "3e", "annee_scolaire": "2025-2026", "programme": "prog"}
    exo = {
        "slug": "ex-1", "titre": "T", "enonce": "Énoncé $120$", "correction": "corr",
        "statut": "valide", "reponse_finale": "$12$", "methode": "m", "etapes": None,
        "chapitres": [], "chapitre_ids": [],
    }
    msgs = tutor.build_tutor_api_messages(
        [{"role": "user", "content": "photo stp"}], eleve, exo, 1, image_dataurl="data:image/jpeg;base64,AAAA"
    )
    assert msgs[0]["role"] == "system"
    assert "<etape" in msgs[0]["content"]  # règle de la balise d'étape dans le prompt
    assert "RÉPONSE DE RÉFÉRENCE" in msgs[0]["content"]
    assert "NIVEAU D'INDICE" in msgs[0]["content"]
    last = msgs[-1]
    assert isinstance(last["content"], list)
    assert last["content"][1]["type"] == "image_url"
    assert last["content"][1]["image_url"]["url"] == "data:image/jpeg;base64,AAAA"


def test_sanitize_history_et_image():
    payload = tutor.ChatRequestIn(
        messages=[tutor.ChatMessageIn(role="user", content="a" * 5000), tutor.ChatMessageIn(role="system", content="x")],
        image=None,
        context=tutor.ChatContextIn(exercice_id="ex-1", niveau_indice=7),
    )
    hist = tutor.sanitize_history(payload.messages)
    assert len(hist[0]["content"]) == tutor.MAX_MESSAGE_CHARS
    assert hist[1]["role"] == "user"  # rôle inconnu ramené à user
    assert tutor.clamp_indice(payload.context.niveau_indice) == 3
    assert tutor.parse_image_dataurl("data:image/png;base64,AAAA") == ("image/png", b"\x00\x00\x00")
    assert tutor.parse_image_dataurl("data:text/html;base64,AAAA") == (None, None)
    assert tutor.parse_image_dataurl("pas une data url") == (None, None)
    assert tutor.parse_image_dataurl(None) == (None, None)


# ------------------------------------------------------- génération en lot


def test_generation_payload_valide():
    obj = {
        "reponse_finale": "$12$",
        "methode": "algorithme d'Euclide",
        "etapes": ["Décomposer 120", "Décomposer 84", "Commun"],
        "statut": "brouillon",
    }
    assert tutor.validate_generation_payload(obj) == []
    norm = tutor.normalize_generation_payload(obj)
    assert norm["reponse_finale"] == "$12$"
    assert json.loads(norm["etapes"]) == ["Décomposer 120", "Décomposer 84", "Commun"]


def test_generation_payload_invalide():
    assert tutor.validate_generation_payload({"reponse_finale": "", "methode": "m", "etapes": ["a", "b"], "statut": "brouillon"})
    assert tutor.validate_generation_payload({"reponse_finale": "x", "methode": "m", "etapes": ["a"], "statut": "brouillon"})
    assert tutor.validate_generation_payload({"reponse_finale": "x", "methode": "m", "etapes": ["a", "b"], "statut": "valide"})
    assert tutor.validate_generation_payload("pas un objet")


def test_build_generation_messages_contient_enonce_et_contrat_json():
    msgs = tutor.build_generation_messages({
        "titre": "PGCD 1", "enonce": "PGCD de 120 et 84 ?", "correction": "corrigé prof",
        "niveau_nom": "3e", "programme": "prog",
    })
    assert msgs[0]["role"] == "system" and "JSON" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "PGCD de 120 et 84 ?" in user
    assert "corrigé prof" in user
    assert '"statut": "brouillon"' in user
