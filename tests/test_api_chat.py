"""Test d'intégration de POST /api/chat (front v2) : auth, contrat JSON,
stream de texte brut — sans base de données (accès DB et LLM bouchonnés)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.routes import chat as chat_routes

ELEVE = {
    "id": 1, "login": "lea.d", "prenom": "Léa", "nom": "Dupont",
    "classe_nom": "3A", "niveau_id": 1, "niveau_nom": "3e",
    "annee_scolaire": "2025-2026", "programme": "programme 3e", "est_prof": False,
}
EXO = {
    "id": 2, "niveau_id": 1, "slug": "ex-1", "titre": "PGCD 1",
    "enonce": "PGCD de $120$ et $84$ ?", "correction": "corr",
    "reponse_finale": "$12$", "methode": "Euclide", "etapes": None,
    "statut": "valide", "chapitres": [], "chapitre_ids": [],
    "niveau_nom": "3e", "classe_nom": "3A", "annee_scolaire": "2025-2026",
}


def _patch(monkeypatch, stream_reply=None):
    monkeypatch.setattr(chat_routes, "get_current_eleve", lambda request: ELEVE)
    monkeypatch.setattr(chat_routes, "_get_exercice", lambda slug: EXO if slug == "ex-1" else None)
    if stream_reply is not None:
        async def fake_stream(messages):
            yield stream_reply
        monkeypatch.setattr(chat_routes, "make_stream_fn", lambda **kw: fake_stream)


def test_post_api_chat_stream_texte_brut(monkeypatch):
    reply = '<etape n="1" total="2"/>\nRéfléchis : quel diviseur commun de $120$ et $84$ ?'
    _patch(monkeypatch, stream_reply=reply)
    client = TestClient(app)
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "je bloque"}],
        "image": None,
        "context": {"exercice_id": "ex-1", "niveau_indice": 0, "eleve": "Léa", "classe": "3A"},
    })
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.text == reply
    assert "<etape" in r.text


def test_post_api_chat_sans_session_401(monkeypatch):
    monkeypatch.setattr(chat_routes, "get_current_eleve", lambda request: None)
    client = TestClient(app)
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "x"}],
        "context": {"exercice_id": "ex-1"},
    })
    assert r.status_code == 401


def test_post_api_chat_exercice_inconnu_404(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "x"}],
        "context": {"exercice_id": "inconnu"},
    })
    assert r.status_code == 404


def test_post_api_chat_message_vide_422(monkeypatch):
    _patch(monkeypatch)
    client = TestClient(app)
    r = client.post("/api/chat", json={"messages": [], "image": None, "context": {"exercice_id": "ex-1"}})
    assert r.status_code == 422


def test_post_api_chat_image_invalide_ignoree_mais_200(monkeypatch):
    reply = '<etape n="1" total="2"/>\nRecopie ton calcul en texte stp.'
    _patch(monkeypatch, stream_reply=reply)
    client = TestClient(app)
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "voici ma photo"}],
        "image": "data:text/html;base64,AAAA",
        "context": {"exercice_id": "ex-1", "niveau_indice": 1},
    })
    assert r.status_code == 200
    assert r.text == reply


def test_post_api_chat_autre_niveau_403(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(chat_routes, "_get_exercice", lambda slug: {**EXO, "niveau_id": 99})
    client = TestClient(app)
    r = client.post("/api/chat", json={
        "messages": [{"role": "user", "content": "x"}],
        "context": {"exercice_id": "ex-1"},
    })
    assert r.status_code == 403
