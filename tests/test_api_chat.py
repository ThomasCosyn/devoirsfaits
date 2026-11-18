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


def test_sw_js_servi_avec_scope_racine():
    client = TestClient(app)
    r = client.get("/sw.js")
    assert r.status_code == 200
    assert r.headers["service-worker-allowed"] == "/"
    assert "serviceWorker" not in r.text  # le fichier lui-même, pas la page
    assert "addEventListener('fetch'" in r.text


def test_manifest_pwa_complet():
    client = TestClient(app)
    r = client.get("/static/manifest.webmanifest")
    assert r.status_code == 200
    data = r.json()
    assert data["display"] == "standalone"
    assert data["start_url"] == "/"
    sizes = {i["sizes"] for i in data["icons"]}
    assert "192x192" in sizes and "512x512" in sizes


def test_icones_pwa_presentes():
    client = TestClient(app)
    for path in ("/static/icons/icon-192.png", "/static/icons/icon-512.png", "/static/icons/apple-touch-icon.png"):
        r = client.get(path)
        assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n", path


def test_template_chat_enonce_deplie_par_defaut():
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("app/templates"))
    html = env.get_template("chat.html").render(
        exercice={"titre": "T", "slug": "ex-1", "enonce": "énoncé"},
        eleve={"prenom": "Léa", "classe_nom": "3A"},
        exo_context={"api": "/api/chat", "exercice_id": "ex-1", "titre": "T", "enonce": "énoncé", "eleve": "Léa", "classe": "3A"},
    )
    assert 'class="stmt open"' in html
    assert 'id="stmtToggle" aria-expanded="true"' in html
    assert "manifest.webmanifest" in html
    assert "serviceWorker.register('/sw.js')" in html
    # barre rapide : uniquement « Un indice » et « Je suis bloqué »
    assert html.count('class="qr') == 2
    assert "Je ne comprends pas" not in html
    # plus de bandeau header : seg dans la zone de messages + bouton flottant quitter
    assert "<header" not in html
    assert 'id="seg"' in html and 'class="fab" id="quit"' in html
    assert "streakPill" not in html
