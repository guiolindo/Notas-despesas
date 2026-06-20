"""Helpers e Pydantic models compartilhados entre os sub-routers admin.

Split do antigo `app/routers/admin.py` (1003 linhas) em sub-arquivos
por subdominio (users, departments, audit, maintenance). Este modulo
agrupa o que e usado por mais de um sub-router pra evitar import
circular e duplicacao.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.models import AuditLog, Department, User, UserRole
from app.security.hashing import pseudonymize_ip


ANONYMIZED_EMAIL_DOMAIN = "@desligado.local"


# ─── Pydantic models ─────────────────────────────────────────────────────────


class UserCreateRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: UserRole
    department_id: str | None = None
    manager_id: str | None = None
    submit_directly_to_director: bool = False
    must_change_password: bool = True

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Nome nao pode ser vazio")
        return value

    @field_validator("password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Senha deve ter no minimo 8 caracteres")
        return value

    @field_validator("department_id", "manager_id")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class UserUpdateRequest(BaseModel):
    name: str | None = None
    department_id: str | None = None
    role: UserRole | None = None
    manager_id: str | None = None
    is_active: bool | None = None
    must_change_password: bool | None = None
    submit_directly_to_director: bool | None = None

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("Nome nao pode ser vazio")
        return value

    @field_validator("department_id", "manager_id")
    @classmethod
    def strip_optional(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class ResetPasswordRequest(BaseModel):
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_min_length(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Senha deve ter no minimo 8 caracteres")
        return value


class DepartmentRequest(BaseModel):
    name: str
    description: str | None = None
    director_ids: list[str] = []


# ─── Helpers ─────────────────────────────────────────────────────────────────


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Request) -> str | None:
    raw = request.client.host if request.client else None
    return pseudonymize_ip(raw)


def client_port(request: Request) -> int | None:
    return request.client.port if request.client else None


def utc_iso(dt) -> str | None:
    """Marca datetime naive como UTC e serializa em ISO (com +00:00).

    Backend grava now_utc() em UTC mas as colunas sao naive — sem marcar tz,
    o JS interpreta como hora local e exibe horarios errados (3h adiantadas
    no fuso de Brasilia).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def is_anonymized(user: User) -> bool:
    """Usuario foi pseudonimizado via LGPD (email purged-* @desligado.local)."""
    return bool(user.email and user.email.lower().endswith(ANONYMIZED_EMAIL_DOMAIN))


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "department_id": user.department_id,
        "department_name": user.department_obj.name if user.department_obj else None,
        "submit_directly_to_director": getattr(user, "submit_directly_to_director", False),
        "is_active": user.is_active,
        "is_anonymized": is_anonymized(user),
        "created_at": utc_iso(user.created_at),
        "last_login": utc_iso(user.last_login),
        "login_attempts": user.login_attempts,
        "blocked_until": utc_iso(user.blocked_until),
        "must_change_password": user.must_change_password,
        "manager_id": user.manager_id,
        "manager_name": user.manager.name if user.manager else None,
    }


def add_audit_log(
    db: Session,
    request: Request,
    current_user: User,
    action: str,
    resource_id: str,
    detail: str,
    resource_type: str = "User",
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            ip_address=client_ip(request),
            source_port=client_port(request),
            http_method=request.method,
            user_agent=request.headers.get("user-agent"),
            timestamp=now_utc(),
            success=True,
            detail=detail,
        )
    )


def ensure_manager_exists(db: Session, manager_id: str | None) -> None:
    if not manager_id:
        return
    manager = db.query(User).filter(User.id == manager_id, User.role == UserRole.MANAGER).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gestor nao encontrado")


def ensure_department_exists(db: Session, department_id: str | None) -> None:
    if not department_id:
        return
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Setor nao encontrado")


def validate_user_structure(
    role: UserRole,
    department_id: str | None,
    manager_id: str | None,
    submit_directly_to_director: bool,
) -> None:
    """Valida que o usuario tem todos os vinculos necessarios para o fluxo funcionar.

    Regras:
    - ADMIN: nao precisa de setor (acesso global)
    - EMPLOYEE: precisa de setor + gestor (ou submit_directly_to_director=True)
    - MANAGER / DIRECTOR / FINANCE: precisam de setor
    """
    needs_department = role in {UserRole.EMPLOYEE, UserRole.MANAGER, UserRole.DIRECTOR, UserRole.FINANCE}
    if needs_department and not department_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Setor e obrigatorio para este perfil. Selecione um setor antes de salvar.",
        )
    if role == UserRole.EMPLOYEE and not manager_id and not submit_directly_to_director:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Funcionario precisa de um gestor cadastrado. "
                "Selecione um gestor ou marque 'Envia notas direto ao diretor'."
            ),
        )


def notify_directors_peer(
    db: Session,
    actor: User,
    action_label: str,
    target: User,
    exclude_target: bool = True,
) -> int:
    """Dispara emails async para todos os diretores ativos avisando que um
    movimento sensivel aconteceu no perfil de diretor. Se nao houver diretor
    ativo (ex: primeiro cadastro), avisa todos os admins ativos como fallback.

    Retorna a quantidade de avisos enviados.
    """
    from app.services import email_service

    q = db.query(User).filter(
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
    )
    if exclude_target and target:
        q = q.filter(User.id != target.id)
    recipients = q.all()

    if not recipients:
        # Fallback: avisa admins (primeiro diretor sendo cadastrado, p.ex)
        recipients = (
            db.query(User)
            .filter(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != actor.id)
            .all()
        )

    if not recipients:
        return 0

    now_br = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M")
    count = 0
    for r in recipients:
        if not r.email or r.email.lower().endswith(ANONYMIZED_EMAIL_DOMAIN):
            continue
        subject, html, text = email_service.template_director_peer_notify(
            recipient_name=r.name or "",
            actor_name=actor.name or actor.email,
            action_label=action_label,
            target_name=target.name or "(sem nome)",
            target_email=target.email or "(sem email)",
            occurred_at_br=now_br,
        )
        email_service.send_email_async(r.email, subject, html, text)
        count += 1
    return count


def active_admins_except(db: Session, user_id: str) -> int:
    return (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user_id)
        .count()
    )
