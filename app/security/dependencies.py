from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.jwt import decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def token_is_pre_password_change(user: User, token_iat: int | float | None) -> bool:
    """True se o token foi emitido ANTES da ultima troca de senha do usuario.

    Helper compartilhado por access tokens (get_current_user), refresh tokens
    (auth.refresh_token) e page guards (page_auth._get_user_from_cookie). Sem
    isso, reset/troca de senha invalida o access em uso mas o refresh em cookie
    continua emitindo access tokens novos por ate 7 dias. CVE classica.
    """
    if not user.password_changed_at or token_iat is None:
        return False
    pwd_changed = user.password_changed_at
    if pwd_changed.tzinfo is None:
        pwd_changed = pwd_changed.replace(tzinfo=timezone.utc)
    try:
        token_emitted_at = datetime.fromtimestamp(float(token_iat), timezone.utc)
    except (TypeError, ValueError, OSError):
        return False
    return token_emitted_at < pwd_changed


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    payload = decode_token(token, expected_type="access")
    user_id: str | None = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao invalida. Faca login novamente.",
        )

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario nao encontrado",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo",
        )

    # Invalida tokens emitidos ANTES da ultima troca de senha (defesa contra
    # token sequestrado em caso de reset por admin/usuario).
    if token_is_pre_password_change(user, payload.get("iat")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao expirada (senha foi alterada). Faca login novamente.",
        )
    return user


def require_role(*roles: str):
    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role.value not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Permissao insuficiente",
            )
        return current_user

    return checker
