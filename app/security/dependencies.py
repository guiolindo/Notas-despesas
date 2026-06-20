from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.jwt import decode_token


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

# Endpoints que continuam acessiveis mesmo com must_change_password=True.
# Tudo fora desta lista e bloqueado em get_current_user com HTTP 428 ate o
# usuario trocar a senha. Sem isto, cliente customizado bypassa o redirect
# do frontend e usa a conta com a senha provisoria (P1-8 da auditoria).
_PASSWORD_CHANGE_ALLOWED_PATHS = frozenset({
    "/auth/me",
    "/auth/change-password",
    "/auth/logout",
})


def _token_iat_to_dt(token_iat: int | float | None) -> datetime | None:
    if token_iat is None:
        return None
    try:
        return datetime.fromtimestamp(float(token_iat), timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


def token_is_pre_password_change(user: User, token_iat: int | float | None) -> bool:
    """True se o token foi emitido ANTES da ultima troca de senha do usuario.

    Helper compartilhado por access tokens (get_current_user), refresh tokens
    (auth.refresh_token) e page guards (page_auth._get_user_from_cookie). Sem
    isso, reset/troca de senha invalida o access em uso mas o refresh em cookie
    continua emitindo access tokens novos por ate 7 dias. CVE classica.

    Tolerancia de 2 segundos: `iat` no JWT e gravado em SEGUNDOS (inteiro),
    enquanto `password_changed_at` no DB tem precisao de microsegundo. Sem a
    margem, login imediato apos troca/reset de senha pode falhar com falso
    positivo (iat truncado vira ~500ms menor que password_changed_at).
    Tolerancia descoberta pelos testes pytest — antes era apenas `<`.
    """
    if not user.password_changed_at:
        return False
    token_dt = _token_iat_to_dt(token_iat)
    if token_dt is None:
        return False
    pwd_changed = user.password_changed_at
    if pwd_changed.tzinfo is None:
        pwd_changed = pwd_changed.replace(tzinfo=timezone.utc)
    delta = (pwd_changed - token_dt).total_seconds()
    return delta > 2.0


def token_is_pre_logout(user: User, token_iat: int | float | None) -> bool:
    """True se o token foi emitido ANTES do ultimo logout explicito.

    Pentest jun/2026 (issue #SEC-5): logout apagava o cookie refresh mas o
    access continuava valido ate expirar. Agora /auth/logout grava
    session_invalidated_at no User; tokens com iat anterior sao rejeitados.

    SEM tolerancia (diferente do password_changed_at): qualquer token cujo
    iat seja anterior ao timestamp de logout e suspeito e tem que cair.
    Considera o iat como o COMECO do segundo gravado no JWT (truncagem)
    — pra ser conservador na revogacao, adicionamos 1s ao token_dt antes
    de comparar (assim, token cujo segundo == segundo do logout ainda e
    revogado).
    """
    invalidated_at = getattr(user, "session_invalidated_at", None)
    if not invalidated_at:
        return False
    token_dt = _token_iat_to_dt(token_iat)
    if token_dt is None:
        return False
    if invalidated_at.tzinfo is None:
        invalidated_at = invalidated_at.replace(tzinfo=timezone.utc)
    # Comparacao estrita. Sem tolerancia: qualquer token emitido antes do
    # logout (mesmo no mesmo segundo, ja que iat e arredondado pra baixo)
    # deve cair. False positives so afetam quem fizer login + logout na
    # mesma fracao de segundo, cenario sem interesse pratico.
    return invalidated_at > token_dt


def get_current_user(
    request: Request,
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
    # Invalida tokens emitidos ANTES do ultimo logout. Pentest jun/2026
    # (#SEC-5): sem isso, logout deixava access valido ate expirar (~1h),
    # mantendo atacante com token roubado na sessao.
    if token_is_pre_logout(user, payload.get("iat")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao encerrada. Faca login novamente.",
        )

    # P1-8: bloqueia uso da API enquanto usuario tem senha provisoria. Antes,
    # a obrigacao so existia no frontend (redirect). Cliente direto via curl
    # ou integracao customizada conseguia operar com senha temporaria.
    if getattr(user, "must_change_password", False):
        if request.url.path not in _PASSWORD_CHANGE_ALLOWED_PATHS:
            raise HTTPException(
                status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                detail=(
                    "Voce precisa trocar a senha antes de executar acoes. "
                    "Acesse seu perfil e defina uma nova senha."
                ),
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


def require_password_changed(current_user: User = Depends(get_current_user)) -> User:
    """Bloqueia endpoints sensiveis enquanto a flag must_change_password do
    usuario estiver True.

    Antes (P1-8 da auditoria), a obrigacao de trocar senha era imposta
    APENAS no frontend (redirect). Quem chamasse a API direta com curl ou
    cliente customizado conseguia executar qualquer acao com a senha
    provisoria. Esta dependency aplica a regra no backend.

    Usar como Depends adicional em rotas que NAO sao /auth/me,
    /auth/change-password, /auth/logout. O codigo 428 ('Precondition
    Required') sinaliza pro frontend que a sessao precisa de uma etapa
    extra antes de prosseguir.
    """
    if getattr(current_user, "must_change_password", False):
        raise HTTPException(
            status_code=status.HTTP_428_PRECONDITION_REQUIRED,
            detail=(
                "Voce precisa trocar a senha antes de executar acoes. "
                "Acesse seu perfil e defina uma nova senha."
            ),
        )
    return current_user
