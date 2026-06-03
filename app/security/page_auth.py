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
from app.security.dependencies import token_is_pre_password_change
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
    # Bloqueia page guard de aceitar refresh emitido antes da ultima troca de
    # senha. Sem isso, navegar pelas paginas HTML continua funcionando ate o
    # cookie expirar (7d), mesmo apos reset/troca. Mesmo bug do /refresh em P0.
    if token_is_pre_password_change(user, payload.get("iat")):
        return None
    return user


def clear_invalid_refresh_cookie(response: Response) -> None:
    """Limpa cookie de refresh em resposta HTML — usado quando page guard
    detecta refresh invalido (senha trocou). Sem isso, navegador segue
    mandando o cookie ate expirar."""
    response.delete_cookie(key="refresh_token")


def _redirect_login_clear_cookie() -> RedirectResponse:
    """Helper: redirect pra /login e tambem apaga cookie de refresh (que pode
    estar invalido por troca de senha)."""
    redirect = RedirectResponse(url="/login", status_code=302)
    clear_invalid_refresh_cookie(redirect)
    return redirect


def require_page_login(request: Request, db: Session) -> User | Response:
    """Garante que existe usuario logado. Retorna User ou RedirectResponse(/login)."""
    user = _get_user_from_cookie(request, db)
    if not user:
        return _redirect_login_clear_cookie()
    return user


def require_page_role(request: Request, db: Session, *roles: str) -> User | Response:
    """Garante que o usuario tem um dos roles permitidos.

    Retorna:
    - User se autorizado
    - RedirectResponse para /login se nao logado (cookie e limpo, caso esteja invalido)
    - TemplateResponse 403 se logado mas sem permissao
    """
    # Import local para evitar ciclo (app.main importa pages que importaria isto na inicializacao)
    from app.main import templates

    user = _get_user_from_cookie(request, db)
    if not user:
        return _redirect_login_clear_cookie()
    if roles and user.role.value not in roles:
        return templates.TemplateResponse(
            request,
            "403.html",
            {"user_role": user.role.value, "user_name": user.name},
            status_code=403,
        )
    return user
