from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, HTTPException, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.database import engine, get_db
from app.models import AuditLog, User
from app.security.dependencies import get_current_user, token_is_pre_password_change
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


def _clear_refresh_cookie(response: Response) -> None:
    """Apaga o cookie de refresh num Response normal (logout/200)."""
    response.delete_cookie(key="refresh_token")


# Set-Cookie pra apagar o refresh quando estamos lancando HTTPException.
# IMPORTANTE: `response.delete_cookie()` ANTES de `raise HTTPException()`
# nao funciona — FastAPI descarta a Response da rota e gera nova a partir
# da excecao. Por isso o cookie precisa entrar via `headers=...` da propria
# excecao. Bug encontrado pelos testes pytest, nao em producao ainda.
def _clear_refresh_cookie_header(secure: bool) -> dict:
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


def _refresh_unauthorized(detail: str) -> HTTPException:
    """401 com Set-Cookie limpando o refresh — usado pelos 4 ramos de
    falha do /refresh."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers=_clear_refresh_cookie_header(
            secure=settings.ENVIRONMENT.upper() == "PROD",
        ),
    )


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
        raise _refresh_unauthorized(exc.detail) from exc

    user_id = payload.get("sub")
    if not user_id:
        raise _refresh_unauthorized("Sessao invalida. Faca login novamente.")

    # Revalida o usuario no DB. Sem isso, conta desativada/bloqueada/anonimizada
    # ou role rebaixado continuariam com access token novo por ate 7 dias.
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise _refresh_unauthorized("Usuario invalido")

    blocked_until = _as_utc(user.blocked_until)
    now = datetime.now(timezone.utc)
    if blocked_until and blocked_until > now:
        # Conta bloqueada: nao apaga cookie ainda (bloqueio e temporario),
        # mas tambem nao emite token novo.
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Conta bloqueada")

    # Invalida refresh emitido ANTES da ultima troca/reset de senha. Sem isso,
    # cliente comprometido continua renovando sessao por ate 7 dias mesmo apos
    # vitima trocar a senha (P0 da auditoria).
    if token_is_pre_password_change(user, payload.get("iat")):
        raise _refresh_unauthorized("Sessao expirada (senha foi alterada). Faca login novamente.")

    # Le role do DB, nao do token (defesa contra rebaixamento ignorado)
    access_token = create_access_token({"sub": user.id, "role": user.role.value})
    return {"access_token": access_token, "token_type": "bearer"}


@router.post("/logout")
def logout(response: Response):
    _clear_refresh_cookie(response)
    return {"message": "Logout realizado"}


# ─── Preferencias do proprio usuario ───────────────────────────────────────

class AvailabilityRequest(BaseModel):
    unavailable: bool
    # Cada role tem seu proprio campo de substituto; o backend aplica o
    # que faz sentido pro role de current_user e ignora o outro.
    substitute_director_id: str | None = None  # apenas DIRECTOR usa
    substitute_manager_id: str | None = None   # apenas MANAGER usa


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


# ─── Esqueci minha senha (codigo por email) ────────────────────────────────

class ForgotPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=255)


class ResetPasswordRequest(BaseModel):
    email: EmailStr = Field(max_length=255)
    code: str = Field(min_length=6, max_length=6)
    new_password: str = Field(min_length=8)


@router.post("/forgot-password")
def forgot_password(
    body: ForgotPasswordRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Gera codigo de 6 digitos e envia por email.

    Protecoes:
    - Resposta SEMPRE 200 com mensagem fixa (anti-enumeracao por conteudo)
    - **Tempo de resposta constante**: TODO o trabalho pesado (lookup,
      bcrypt do codigo, INSERT, envio SMTP) acontece em BackgroundTasks
      depois da resposta. Pentest jun/2026 mediu 6s vs 10ms entre email
      existente e nao-existente — o caso "existe" pagava bcrypt + DB
      writes na resposta sincrona, vazando a existencia por timing.
    - Throttle: 1 pedido por 60 segundos por email (evita spam SMTP)
    """
    _email_raw = body.email

    def _process_request_async() -> None:
        # Roda depois da resposta — todo o caminho "user existe" + bcrypt
        # + DB writes + send_email fica fora do tempo de resposta visto
        # pelo atacante. Sessao DB propria pra nao depender do scope da
        # request original.
        import secrets as _secrets
        import uuid as _uuid
        from app.database import SessionLocal
        from app.models import PasswordResetCode
        from app.services import email_service

        try:
            email = sanitize_email(_email_raw)
        except Exception:  # noqa: BLE001
            return

        with SessionLocal() as session:
            user = (
                session.query(User)
                .filter(User.email == email, User.is_active.is_(True))
                .first()
            )
            if not user:
                return
            now = datetime.now(timezone.utc)
            recent = (
                session.query(PasswordResetCode)
                .filter(
                    PasswordResetCode.user_id == user.id,
                    PasswordResetCode.created_at > now - timedelta(seconds=60),
                )
                .order_by(PasswordResetCode.created_at.desc())
                .first()
            )
            if recent:
                return  # throttle silencioso
            code = f"{_secrets.randbelow(10**6):06d}"
            expires = now + timedelta(minutes=15)
            session.query(PasswordResetCode).filter(
                PasswordResetCode.user_id == user.id,
                PasswordResetCode.used_at.is_(None),
            ).update({"used_at": now})
            session.add(PasswordResetCode(
                id=str(_uuid.uuid4()),
                user_id=user.id,
                code_hash=hash_password(code),
                expires_at=expires,
                attempts=0,
            ))
            session.commit()
            try:
                subject, html, text = email_service.template_password_reset_code(
                    user.name, code, minutes_valid=15,
                )
                email_service.send_email(session, user.email, subject, html, text)
            except Exception:  # noqa: BLE001
                pass

    background_tasks.add_task(_process_request_async)
    return {"message": "Se o email estiver cadastrado, voce recebera um codigo em alguns segundos."}


@router.post("/reset-password")
def reset_password(
    body: ResetPasswordRequest,
    db: Session = Depends(get_db),
):
    from app.models import PasswordResetCode

    # Valida complexidade ANTES de tocar no DB. Senao, atacante distingue
    # email cadastrado de nao cadastrado pelo status code 422 vs 400.
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="Codigo invalido ou expirado")
    if not any(c.isalpha() for c in body.new_password) or not any(c.isdigit() for c in body.new_password):
        raise HTTPException(status_code=400, detail="Codigo invalido ou expirado")

    email = sanitize_email(body.email)
    user = db.query(User).filter(User.email == email, User.is_active.is_(True)).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Codigo invalido ou expirado")

    now = datetime.now(timezone.utc)
    # Busca codigos ativos do usuario que ainda nao excederam tentativas
    MAX_ATTEMPTS = 5
    active_codes = (
        db.query(PasswordResetCode)
        .filter(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > now,
        )
        .all()
    )
    # Filtra os que ja foram bloqueados por tentativas
    available_codes = [c for c in active_codes if (c.attempts or 0) < MAX_ATTEMPTS]
    if not available_codes:
        # Se havia codigos mas todos exauriram tentativas, registra
        if active_codes:
            db.add(AuditLog(
                user_id=user.id,
                action="PASSWORD_RESET_BRUTE_FORCE_BLOCKED",
                resource_type="USER",
                resource_id=user.id,
                timestamp=now,
                success=False,
                detail=f"Codigo invalidado apos {MAX_ATTEMPTS} tentativas",
            ))
            db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido, expirado ou excedeu tentativas. Solicite um novo codigo.",
        )

    matched = None
    for c in available_codes:
        if verify_password(body.code, c.code_hash):
            matched = c
            break

    if not matched:
        # Incrementa attempts em TODOS os codigos ativos do user
        # (atacante nao sabe qual codigo esta tentando — protege todos)
        for c in available_codes:
            c.attempts = (c.attempts or 0) + 1
            if c.attempts >= MAX_ATTEMPTS:
                c.used_at = now  # invalida
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Codigo invalido ou expirado",
        )

    # Aplica
    matched.used_at = now
    user.hashed_password = hash_password(body.new_password)
    user.password_changed_at = datetime.now(timezone.utc)
    user.must_change_password = False
    user.login_attempts = 0
    user.blocked_until = None
    db.add(AuditLog(
        user_id=user.id,
        action="PASSWORD_RESET_BY_CODE",
        resource_type="USER",
        resource_id=user.id,
        timestamp=now,
        success=True,
    ))
    db.commit()
    return {"message": "Senha redefinida com sucesso. Faca login com a nova senha."}


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
        "unavailable_for_notes": getattr(current_user, "unavailable_for_notes", False),
        "substitute_director_id": getattr(current_user, "substitute_director_id", None),
        "substitute_manager_id": getattr(current_user, "substitute_manager_id", None),
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
    current_user.password_changed_at = datetime.now(timezone.utc)
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
