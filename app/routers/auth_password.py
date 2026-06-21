"""Endpoints de senha: forgot, reset, change.

Split do `auth.py` em jun/2026 (Fase 1.1).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, User
from app.security.dependencies import get_current_user
from app.security.hashing import hash_password, verify_password

from app.routers.auth_helpers import (
    ChangePasswordRequest,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    sanitize_email,
)


router = APIRouter()


# ─── /auth/forgot-password ────────────────────────────────────────────────────


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


# ─── /auth/reset-password ─────────────────────────────────────────────────────


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


# ─── /auth/change-password ────────────────────────────────────────────────────


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
    # Pentest jun/2026 (#SEC-8): proibe trocar a senha pela mesma. Sem
    # esta checagem, usuario com must_change_password=True conseguia
    # "trocar" pra mesma senha e bypassar a obrigacao de virar fluxo —
    # bypass total da politica de reset forcado pelo admin.
    if verify_password(body.new_password, current_user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A nova senha deve ser diferente da senha atual.",
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
