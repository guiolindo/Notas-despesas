"""Endpoints de sessao: login, refresh, logout, me, availability.

Split do `auth.py` em jun/2026 (Fase 1.1).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import AuditLog, User
from app.security.dependencies import get_current_user
from app.security.hashing import verify_password
from app.security.jwt import create_access_token, create_refresh_token, decode_token

from app.routers.auth_helpers import (
    AvailabilityRequest,
    LoginRequest,
    LOGIN_TIMING_DUMMY_HASH,
    as_utc,
    clear_refresh_cookie,
    engine_dialect_supports_for_update,
    refresh_unauthorized,
    sanitize_email,
    user_payload,
)


router = APIRouter()


# ─── Login ────────────────────────────────────────────────────────────────────


@router.post("/login")
def login(
    credentials: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    email = sanitize_email(credentials.email)
    # Lock pessimista evita race em login_attempts quando dois requests caem
    # ao mesmo tempo (incremento perdido + bypass do limite de tentativas).
    # SQLite ignora with_for_update; em PG funciona como SELECT ... FOR UPDATE.
    query = db.query(User).filter(User.email == email)
    if engine_dialect_supports_for_update():
        query = query.with_for_update()
    user = query.first()
    invalid_credentials = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Email ou senha invalidos",
    )

    if not user:
        # Pentest jun/2026 (#SEC-4): user enumeration por timing. Email
        # existente paga bcrypt (~250ms); inexistente cai no short-circuit
        # (~10ms). Mitigacao: pagar bcrypt mesmo no caso "user not found".
        verify_password(credentials.password, LOGIN_TIMING_DUMMY_HASH)
        raise invalid_credentials

    blocked_until = as_utc(user.blocked_until)
    if blocked_until and blocked_until > now:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Conta bloqueada ate {blocked_until.strftime('%H:%M')}",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inativo",
        )

    if not verify_password(credentials.password, user.hashed_password):
        user.login_attempts += 1
        if user.login_attempts >= settings.MAX_LOGIN_ATTEMPTS:
            user.blocked_until = now + timedelta(minutes=settings.LOGIN_BLOCK_MINUTES)
            user.login_attempts = 0
            db.commit()
            # Notifica o titular em background — request retorna sem esperar
            try:
                if user.email:
                    from app.services import email_service
                    subject, html, text = email_service.template_account_blocked(
                        user.name, settings.LOGIN_BLOCK_MINUTES,
                    )
                    email_service.send_email_async(user.email, subject, html, text)
            except Exception:  # noqa: BLE001
                pass
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Conta bloqueada ate {user.blocked_until.strftime('%H:%M')}",
            )
        db.commit()
        raise invalid_credentials

    user.login_attempts = 0
    user.blocked_until = None
    user.last_login = now
    db.commit()
    db.refresh(user)

    payload = user_payload(user)
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        samesite="strict",
        secure=settings.ENVIRONMENT.upper() == "PROD",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 3600,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "name": user.name,
            "role": user.role.value,
            "email": user.email,
            "must_change_password": user.must_change_password,
            "submit_directly_to_director": getattr(user, "submit_directly_to_director", False),
        },
    }


# ─── Refresh ──────────────────────────────────────────────────────────────────


@router.post("/refresh")
def refresh_token(
    response: Response,
    refresh_token_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
):
    if not refresh_token_cookie:
        # Sem cookie nao precisa apagar nada — 401 padrao.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Sessao expirada. Faca login novamente.",
        )

    try:
        payload = decode_token(refresh_token_cookie, expected_type="refresh")
    except HTTPException as exc:
        # Refresh invalido (assinatura, expirou, type errado): limpa cookie
        # pra cliente parar de mandar e cair pra /login.
        raise refresh_unauthorized(exc.detail) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise refresh_unauthorized("Sessao invalida. Faca login novamente.")

    # Revalida o usuario no DB. Sem isso, conta desativada/bloqueada/anonimizada
    # ou role rebaixado continuariam com access token novo por ate 7 dias.
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise refresh_unauthorized("Usuario invalido")

    blocked_until = as_utc(user.blocked_until)
    if blocked_until and blocked_until > datetime.now(timezone.utc):
        raise refresh_unauthorized("Conta bloqueada")

    # Invalida refresh tokens emitidos ANTES da ultima troca de senha.
    from app.security.dependencies import token_is_pre_password_change
    if token_is_pre_password_change(user, payload.get("iat")):
        raise refresh_unauthorized("Sessao expirada (senha foi alterada). Faca login novamente.")

    # Le role do DB, nao do token (defesa contra rebaixamento ignorado)
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    return {"access_token": access_token, "token_type": "bearer"}


# ─── Logout ───────────────────────────────────────────────────────────────────


@router.post("/logout")
def logout(
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Logout: limpa cookie refresh + invalida access tokens emitidos antes
    deste momento.

    Pentest jun/2026 (issue #SEC-5): antes, logout apenas apagava o cookie
    refresh; o access token continuava valido ate expirar (~1h). Atacante
    com token roubado (XSS, MITM) mantinha sessao mesmo apos usuario sair.

    Fix: registra session_invalidated_at no User; get_current_user rejeita
    tokens com iat anterior a esse timestamp. Logout agora revoga de
    verdade — janela de risco reduzida a delta(now, iat) que esta
    sempre proximo de zero.
    """
    clear_refresh_cookie(response)
    try:
        current_user.session_invalidated_at = datetime.now(timezone.utc)
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
    return {"message": "Logout realizado"}


# ─── /auth/me ─────────────────────────────────────────────────────────────────


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    return {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role.value,
        "department_id": current_user.department_id,
        "must_change_password": current_user.must_change_password,
        "submit_directly_to_director": getattr(current_user, "submit_directly_to_director", False),
        "unavailable_for_notes": getattr(current_user, "unavailable_for_notes", False),
        "substitute_director_id": getattr(current_user, "substitute_director_id", None),
        "substitute_manager_id": getattr(current_user, "substitute_manager_id", None),
        "last_login": current_user.last_login.isoformat() if current_user.last_login else None,
    }


# ─── /auth/me/availability ────────────────────────────────────────────────────


def _validate_substitute(
    db: Session,
    current_user: User,
    sub_id: str,
    required_role: str,
) -> User:
    sub = db.query(User).filter(User.id == sub_id).first()
    if not sub or sub.role.value != required_role or not sub.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Substituto invalido. Deve ser outro {required_role.lower()} ativo.",
        )
    if sub.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voce nao pode designar a si mesmo como substituto.",
        )
    return sub


@router.put("/me/availability")
def update_availability(
    body: AvailabilityRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Diretor ou gestor marca a si proprio como temporariamente
    indisponivel — nao recebe novas notas durante ferias / ausencia.

    Pode opcionalmente designar um substituto da mesma role: quando
    indisponivel e com substituto configurado, novas submissoes que tentem
    rotear pra ele caem direto no substituto. Sem isso, a submissao falha
    com mensagem clara (defesa contra fila represada por gestor em ferias —
    P1-9 da auditoria).
    """
    role = current_user.role.value
    if role not in {"DIRECTOR", "MANAGER"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas gestores e diretores podem pausar recebimento.",
        )
    current_user.unavailable_for_notes = body.unavailable

    if role == "DIRECTOR":
        if body.substitute_director_id:
            sub = _validate_substitute(db, current_user, body.substitute_director_id, "DIRECTOR")
            current_user.substitute_director_id = sub.id
        else:
            current_user.substitute_director_id = None
    elif role == "MANAGER":
        if body.substitute_manager_id:
            sub = _validate_substitute(db, current_user, body.substitute_manager_id, "MANAGER")
            current_user.substitute_manager_id = sub.id
        else:
            current_user.substitute_manager_id = None

    db.commit()
    return {
        "unavailable_for_notes": current_user.unavailable_for_notes,
        "substitute_director_id": current_user.substitute_director_id,
        "substitute_manager_id": getattr(current_user, "substitute_manager_id", None),
        "message": (
            "Voce esta marcado como INDISPONIVEL — nao recebera novas notas."
            if body.unavailable else
            "Voce esta DISPONIVEL — recebera notas normalmente."
        ),
    }
