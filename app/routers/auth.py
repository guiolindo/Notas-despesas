from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.models import AuditLog, User
from app.security.dependencies import get_current_user
from app.security.hashing import hash_password, verify_password
from app.security.jwt import create_access_token, create_refresh_token, decode_token


router = APIRouter()


def engine_dialect_supports_for_update() -> bool:
    """SQLite ignora SELECT ... FOR UPDATE; PostgreSQL/MySQL/etc. usam."""
    return engine.dialect.name != "sqlite"


class LoginRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=1, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1)
    new_password: str = Field(min_length=8)


def sanitize_email(email: str) -> str:
    return email.strip().lower()[:255]


def _as_utc(value: datetime | None) -> datetime | None:
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
        raise invalid_credentials

    blocked_until = _as_utc(user.blocked_until)
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


@router.post("/refresh")
def refresh_token(
    refresh_token_cookie: str | None = Cookie(default=None, alias="refresh_token"),
    db: Session = Depends(get_db),
):
    if not refresh_token_cookie:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token ausente",
        )

    payload = decode_token(refresh_token_cookie, expected_type="refresh")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token invalido")

    # Revalida o usuario no DB. Sem isso, conta desativada/bloqueada/anonimizada
    # ou role rebaixado continuariam com access token novo por ate 7 dias.
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Usuario invalido")

    blocked_until = _as_utc(user.blocked_until)
    now = datetime.now(timezone.utc)
    if blocked_until and blocked_until > now:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta bloqueada")

    # Le role do DB, nao do token (defesa contra rebaixamento ignorado)
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(key="refresh_token")
    return {"message": "Logout realizado"}


@router.get("/me")
def me(current_user: User = Depends(get_current_user)):
    data = {
        "id": current_user.id,
        "name": current_user.name,
        "email": current_user.email,
        "role": current_user.role.value,
        "department_id": current_user.department_id,
        "must_change_password": current_user.must_change_password,
        "submit_directly_to_director": getattr(current_user, "submit_directly_to_director", False),
        "last_login": _as_utc(current_user.last_login).isoformat() if current_user.last_login else None,
    }
    if current_user.must_change_password:
        data["action_required"] = "change_password"
    return data


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Senha atual incorreta")
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nova senha deve ter minimo 8 caracteres",
        )
    if not any(char.isalpha() for char in body.new_password) or not any(
        char.isdigit() for char in body.new_password
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nova senha deve conter letra e numero",
        )

    current_user.hashed_password = hash_password(body.new_password)
    current_user.must_change_password = False
    db.add(
        AuditLog(
            user_id=current_user.id,
            action="CHANGE_PASSWORD",
            resource_type="USER",
            resource_id=current_user.id,
            timestamp=datetime.now(timezone.utc),
            success=True,
        )
    )
    db.commit()
    return {"message": "Senha alterada com sucesso"}
