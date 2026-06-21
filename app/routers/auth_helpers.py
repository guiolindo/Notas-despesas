"""Helpers compartilhados entre auth_session.py e auth_password.py.

Split do antigo `app/routers/auth.py` (594 linhas) em jun/2026 (Fase 1.1
do plan-refactor-master.md). Concentra:
  - Pydantic request models
  - sanitize_email
  - dummy bcrypt hash pra resposta de tempo constante no login
  - helpers de cookie refresh (clear + clear via header)
  - user_payload pro JWT
"""
from datetime import datetime, timezone

from fastapi import HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field

from app.config import settings
from app.database import engine
from app.models import User


# ─── Pydantic request models ─────────────────────────────────────────────────


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


class AvailabilityRequest(BaseModel):
    unavailable: bool
    # Cada role tem seu proprio campo de substituto; o backend aplica o
    # que faz sentido pro role de current_user e ignora o outro.
    substitute_director_id: str | None = None  # apenas DIRECTOR usa
    substitute_manager_id: str | None = None   # apenas MANAGER usa


class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=255)


class ResetPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)


# ─── Helpers ─────────────────────────────────────────────────────────────────


def engine_dialect_supports_for_update() -> bool:
    """SQLite ignora SELECT ... FOR UPDATE; PostgreSQL/MySQL/etc. usam."""
    return engine.dialect.name != "sqlite"


def sanitize_email(email: str) -> str:
    return email.strip().lower()[:255]


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def user_payload(user: User) -> dict:
    # Minimizacao de dados (LGPD): JWT carrega apenas o necessario para autenticar
    return {
        "sub": user.id,
        "role": user.role.value,
    }


# Hash bcrypt fixo de "decoy_password_for_timing_attack_defense". Usado
# em /login quando o email nao existe — paga o custo do bcrypt pra
# tempo de resposta nao revelar se a conta existe. Gerado uma vez no
# import; nao e segredo (nenhuma senha real bate com ele).
# Pentest jun/2026 #SEC-4.
LOGIN_TIMING_DUMMY_HASH = (
    "$2b$12$N9qo8uLOickgx2ZMRZoMyeIjZAgcfl7p92ldGxad68LJZdL17lhWy"
)


# ─── Refresh cookie helpers ──────────────────────────────────────────────────


def clear_refresh_cookie(response: Response) -> None:
    """Apaga o cookie de refresh num Response normal (logout/200)."""
    response.delete_cookie(key="refresh_token")


# Set-Cookie pra apagar o refresh quando estamos lancando HTTPException.
# IMPORTANTE: `response.delete_cookie()` ANTES de `raise HTTPException()`
# nao funciona — FastAPI descarta a Response da rota e gera nova a partir
# da excecao. Por isso o cookie precisa entrar via `headers=...` da propria
# excecao. Bug encontrado pelos testes pytest, nao em producao ainda.
def clear_refresh_cookie_header(secure: bool) -> dict:
    parts = [
        'refresh_token=""',
        "Path=/",
        "Max-Age=0",
        "HttpOnly",
        "SameSite=strict",
    ]
    if secure:
        parts.append("Secure")
    return {"set-cookie": "; ".join(parts)}


def refresh_unauthorized(detail: str) -> HTTPException:
    """401 com Set-Cookie limpando o refresh — usado pelos 4 ramos de
    falha do /refresh."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=clear_refresh_cookie_header(
            secure=settings.ENVIRONMENT.upper() == "PROD",
        ),
    )
