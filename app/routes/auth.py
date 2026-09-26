from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.db import query_one
from app.security import verify_password, set_session_cookie, clear_session_cookie

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def get_current_eleve(request: Request):
    from app.security import read_session_token, COOKIE_NAME

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    eleve_id = read_session_token(token)
    if not eleve_id:
        return None
    return query_one(
        """
        SELECT e.id, e.login, e.nom, e.prenom,
               c.nom AS classe_nom, c.id AS classe_id,
               c.annee_scolaire, c.programme
        FROM devoirsfaits.eleves e JOIN devoirsfaits.classes c ON c.id = e.classe_id
        WHERE e.id = %s AND e.actif
        """,
        (eleve_id,),
    )


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request, next: str = "/"):
    if get_current_eleve(request):
        return RedirectResponse(next, status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"next": next, "error": None}
    )


@router.post("/login")
async def login(
    request: Request,
    login_name: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
):
    row = query_one(
        """
        SELECT e.id, e.login, e.password_hash
        FROM devoirsfaits.eleves e
        WHERE e.login = %s AND e.actif
        """,
        (login_name.strip().lower(),),
    )
    if not row or not verify_password(password, row["password_hash"]):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"next": next, "error": "Identifiant ou mot de passe incorrect."},
            status_code=401,
        )
    if not next.startswith("/"):
        next = "/"
    response = RedirectResponse(next, status_code=303)
    set_session_cookie(request, response, row["id"])
    return response


@router.get("/logout")
async def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_session_cookie(response)
    return response
