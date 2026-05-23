"""Autenticacao server-side para rotas HTML.

Diferente das APIs (que usam Bearer header), as paginas HTML sao requisitadas
diretamente pelo navegador, entao a autenticacao acontece via cookie HttpOnly
'refresh_token' setado no login.

Uso tipico em pages.py:

    @router.get("/admin/users")
    def admin_users_page(request: Request, db: Session = Depends(get_db)):
        guard = require_page_role(request, db, "ADMIN")
        if not isinstance(guard, User):
            return guard
        return templates.TemplateResponse(request, "admin/users.html")
"""
from __future__ import annotations

from fastapi import Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.models import User
from app.security.jwt import decode_token


def _get_user_from_cookie(request: Request, db: Session) -> User | None:
    token = request.cookies.get("refresh_token")
    if not token:
        return None
    try:
        payload = decode_token(token, expected_type="refresh")
    except Exception:
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        return None
    return user


def require_page_login(request: Request, db: Session) -> User | Response:
    """Garante que existe usuario logado. Retorna User ou RedirectResponse(/login)."""
    user = _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return user


def require_page_role(request: Request, db: Session, *roles: str) -> User | Response:
    """Garante que o usuario tem um dos roles permitidos.

    Retorna:
    - User se autorizado
    - RedirectResponse para /login se nao logado
    - TemplateResponse 403 se logado mas sem permissao
    """
    # Import local para evitar ciclo (app.main importa pages que importaria isto na inicializacao)
    from app.main import templates

    user = _get_user_from_cookie(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    if roles and user.role.value not in roles:
        return templates.TemplateResponse(
            request,
            "403.html",
            {"user_role": user.role.value, "user_name": user.name},
            status_code=403,
        )
    return user
