import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, EmailStr, field_validator
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Department, User, UserRole
from app.security.dependencies import require_role
from app.security.hashing import hash_password, pseudonymize_ip


router = APIRouter(prefix="/api/admin", tags=["Admin"])


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


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _client_ip(request: Request) -> str | None:
    raw = request.client.host if request.client else None
    return pseudonymize_ip(raw)


def _client_port(request: Request) -> int | None:
    return request.client.port if request.client else None


def _user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "name": user.name,
        "email": user.email,
        "role": user.role.value,
        "department_id": user.department_id,
        "department_name": user.department_obj.name if user.department_obj else None,
        "submit_directly_to_director": getattr(user, "submit_directly_to_director", False),
        "is_active": user.is_active,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "last_login": user.last_login.isoformat() if user.last_login else None,
        "login_attempts": user.login_attempts,
        "blocked_until": user.blocked_until.isoformat() if user.blocked_until else None,
        "must_change_password": user.must_change_password,
        "manager_id": user.manager_id,
        "manager_name": user.manager.name if user.manager else None,
    }


def _add_audit_log(
    db: Session,
    request: Request,
    current_user: User,
    action: str,
    resource_id: str,
    detail: str,
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=current_user.id,
            action=action,
            resource_type="User",
            resource_id=resource_id,
            ip_address=_client_ip(request),
            source_port=_client_port(request),
            http_method=request.method,
            user_agent=request.headers.get("user-agent"),
            timestamp=_now(),
            success=True,
            detail=detail,
        )
    )


def _ensure_manager_exists(db: Session, manager_id: str | None) -> None:
    if not manager_id:
        return
    manager = db.query(User).filter(User.id == manager_id, User.role == UserRole.MANAGER).first()
    if not manager:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Gestor nao encontrado")


def _ensure_department_exists(db: Session, department_id: str | None) -> None:
    if not department_id:
        return
    dept = db.query(Department).filter(Department.id == department_id).first()
    if not dept:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Setor nao encontrado")


def _validate_user_structure(
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


def _active_admins_except(db: Session, user_id: str) -> int:
    return (
        db.query(User)
        .filter(User.role == UserRole.ADMIN, User.is_active.is_(True), User.id != user_id)
        .count()
    )


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    users = db.query(User).order_by(User.name).all()
    return [_user_payload(user) for user in users]


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    body: UserCreateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    email = body.email.lower()
    existing = db.query(User).filter(User.email == email).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email ja cadastrado")

    manager_id = body.manager_id if body.role == UserRole.EMPLOYEE else None
    _ensure_manager_exists(db, manager_id)
    _ensure_department_exists(db, body.department_id)
    _validate_user_structure(
        body.role,
        body.department_id,
        manager_id,
        body.submit_directly_to_director,
    )

    new_user = User(
        id=str(uuid.uuid4()),
        name=body.name.strip(),
        email=email,
        hashed_password=hash_password(body.password),
        role=body.role,
        department_id=body.department_id or None,
        manager_id=manager_id,
        submit_directly_to_director=body.submit_directly_to_director,
        must_change_password=body.must_change_password,
        is_active=True,
    )
    db.add(new_user)
    _add_audit_log(
        db,
        request,
        current_user,
        "CREATE_USER",
        new_user.id,
        f"Criou usuario {new_user.email} com role {new_user.role.value}",
    )
    db.commit()
    db.refresh(new_user)
    return {"id": new_user.id, "message": "Usuario criado com sucesso"}


@router.get("/users/{user_id}")
def get_user(
    user_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")
    return _user_payload(user)


@router.put("/users/{user_id}")
def update_user(
    user_id: str,
    body: UserUpdateRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    # Nunca desativar ou trocar role de um ADMIN por outro ADMIN (proteção estrutural)
    if user.role == UserRole.ADMIN and user.id != current_user.id:
        if body.is_active is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nao e possivel desativar outro administrador",
            )
        if body.role is not None and body.role != UserRole.ADMIN:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nao e possivel remover o perfil de administrador por aqui — contate o suporte tecnico",
            )

    if user.id == current_user.id and body.is_active is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voce nao pode desativar a propria conta",
        )

    removing_last_admin_role = body.role is not None and body.role != UserRole.ADMIN and user.role == UserRole.ADMIN
    deactivating_last_admin = body.is_active is False and user.role == UserRole.ADMIN
    if (removing_last_admin_role or deactivating_last_admin) and _active_admins_except(db, user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel remover o ultimo ADMIN do sistema",
        )

    # Calcula estado final ANTES de aplicar para validar consistencia
    final_role = body.role if body.role is not None else user.role
    final_dept_id = (
        (body.department_id.strip() or None) if body.department_id is not None
        else user.department_id
    )
    final_submit_direct = (
        body.submit_directly_to_director
        if body.submit_directly_to_director is not None
        else getattr(user, "submit_directly_to_director", False)
    )
    # manager_id so se aplica a EMPLOYEE
    if final_role == UserRole.EMPLOYEE:
        if body.manager_id is not None:
            final_manager_id = body.manager_id.strip() or None
        else:
            final_manager_id = user.manager_id
    else:
        final_manager_id = None

    _ensure_department_exists(db, final_dept_id)
    _ensure_manager_exists(db, final_manager_id)
    _validate_user_structure(final_role, final_dept_id, final_manager_id, final_submit_direct)

    changes: list[str] = []
    if body.name is not None:
        user.name = body.name.strip()
        changes.append("name")
    if body.department_id is not None:
        user.department_id = final_dept_id
        changes.append("department_id")
    if body.role is not None:
        user.role = body.role
        if body.role != UserRole.EMPLOYEE:
            user.manager_id = None
        changes.append("role")
    if body.manager_id is not None:
        user.manager_id = final_manager_id
        changes.append("manager_id")
    if body.is_active is not None:
        user.is_active = body.is_active
        if body.is_active:
            user.login_attempts = 0
            user.blocked_until = None
        changes.append("is_active")
    if body.must_change_password is not None:
        user.must_change_password = body.must_change_password
        changes.append("must_change_password")
    if body.submit_directly_to_director is not None:
        user.submit_directly_to_director = body.submit_directly_to_director
        changes.append("submit_directly_to_director")

    _add_audit_log(
        db,
        request,
        current_user,
        "UPDATE_USER",
        user.id,
        f"Editou campos: {', '.join(changes) or 'nenhum'} do usuario {user.email}",
    )
    db.commit()
    return {"message": "Usuario atualizado com sucesso"}


@router.post("/users/{user_id}/reset-password")
def reset_password(
    user_id: str,
    body: ResetPasswordRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    # PROTECAO: nenhum admin pode resetar senha de outro admin (evita sequestro de conta).
    # Cada admin so pode redefinir a propria senha por aqui ou pelo /auth/change-password.
    if user.role == UserRole.ADMIN and user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Nao e possivel redefinir a senha de outro administrador. "
                "O proprio admin deve usar 'Trocar senha' apos login."
            ),
        )

    # Validacao de complexidade consistente com /auth/change-password
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nova senha deve ter no minimo 8 caracteres",
        )
    if not any(c.isalpha() for c in body.new_password) or not any(c.isdigit() for c in body.new_password):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nova senha deve conter pelo menos uma letra e um numero",
        )

    user.hashed_password = hash_password(body.new_password)
    user.must_change_password = True
    user.login_attempts = 0
    user.blocked_until = None
    _add_audit_log(
        db,
        request,
        current_user,
        "RESET_PASSWORD",
        user.id,
        f"Redefiniu senha do usuario {user.email}",
    )
    db.commit()
    return {"message": "Senha redefinida. Usuario deve trocar no proximo login."}


@router.post("/users/{user_id}/unlock")
def unlock_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario nao encontrado")

    user.login_attempts = 0
    user.blocked_until = None
    _add_audit_log(
        db,
        request,
        current_user,
        "UNLOCK_USER",
        user.id,
        f"Desbloqueou usuario {user.email}",
    )
    db.commit()
    return {"message": "Usuario desbloqueado com sucesso"}


@router.get("/audit-logs")
def list_audit_logs(
    page: int = 1,
    per_page: int = 50,
    action: str | None = None,
    user_id: str | None = None,
    success: bool | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    page = max(page, 1)
    per_page = max(min(per_page, 100), 1)
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action.ilike(f"%{action.strip()}%"))
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if success is not None:
        query = query.filter(AuditLog.success.is_(success))

    total = query.count()
    logs = (
        query.order_by(AuditLog.timestamp.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": (total + per_page - 1) // per_page,
        "items": [
            {
                "id": log.id,
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "success": log.success,
                "detail": log.detail,
                "ip_address": log.ip_address,
                "user_id": log.user_id,
                "user_name": log.user.name if log.user else "Sistema",
                "user_email": log.user.email if log.user else None,
            }
            for log in logs
        ],
    }


@router.get("/managers")
def list_managers(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    managers = (
        db.query(User)
        .filter(User.role == UserRole.MANAGER, User.is_active.is_(True))
        .order_by(User.name)
        .all()
    )
    return [{"id": manager.id, "name": manager.name} for manager in managers]


# ─── Departamentos ───────────────────────────────────────────────────────────

class DepartmentRequest(BaseModel):
    name: str
    description: str | None = None
    director_ids: list[str] = []


@router.get("/departments")
def list_departments(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    depts = db.query(Department).order_by(Department.name).all()
    return [
        {
            "id": d.id,
            "name": d.name,
            "description": d.description,
            "members_count": len(d.members),
            "directors": [{"id": dr.id, "name": dr.name} for dr in d.directors],
        }
        for d in depts
    ]


@router.post("/departments", status_code=201)
def create_department(
    body: DepartmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Nome do setor nao pode ser vazio")
    existing = db.query(Department).filter(Department.name == name).first()
    if existing:
        raise HTTPException(400, "Ja existe um setor com este nome")

    dept = Department(id=str(uuid.uuid4()), name=name, description=body.description)
    if body.director_ids:
        directors = db.query(User).filter(
            User.id.in_(body.director_ids), User.role == UserRole.DIRECTOR
        ).all()
        dept.directors = directors

    db.add(dept)
    db.add(AuditLog(
        id=str(uuid.uuid4()), user_id=current_user.id, action="CREATE_DEPARTMENT",
        resource_type="Department", resource_id=dept.id,
        ip_address=_client_ip(request), source_port=_client_port(request),
        http_method=request.method, timestamp=_now(), success=True,
        detail=f"Criou setor {dept.name}",
    ))
    db.commit()
    return {"id": dept.id, "message": "Setor criado com sucesso"}


@router.put("/departments/{dept_id}")
def update_department(
    dept_id: str,
    body: DepartmentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(404, "Setor nao encontrado")

    name = body.name.strip()
    if name:
        dept.name = name
    if body.description is not None:
        dept.description = body.description
    if body.director_ids is not None:
        directors = db.query(User).filter(
            User.id.in_(body.director_ids), User.role == UserRole.DIRECTOR
        ).all()
        dept.directors = directors

    db.add(AuditLog(
        id=str(uuid.uuid4()), user_id=current_user.id, action="UPDATE_DEPARTMENT",
        resource_type="Department", resource_id=dept.id,
        ip_address=_client_ip(request), source_port=_client_port(request),
        http_method=request.method, timestamp=_now(), success=True,
        detail=f"Editou setor {dept.name}",
    ))
    db.commit()
    return {"message": "Setor atualizado com sucesso"}


@router.delete("/departments/{dept_id}", status_code=204)
def delete_department(
    dept_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    dept = db.query(Department).filter(Department.id == dept_id).first()
    if not dept:
        raise HTTPException(404, "Setor nao encontrado")
    if dept.members:
        member_count = len(dept.members)
        raise HTTPException(
            400,
            f"Nao e possivel excluir setor com {member_count} usuario(s) vinculado(s). "
            "Realoque-os para outro setor primeiro.",
        )
    if dept.directors:
        raise HTTPException(
            400,
            "Nao e possivel excluir setor com diretores designados. "
            "Remova os diretores do setor antes.",
        )
    _add_audit_log(
        db, request, current_user,
        "DELETE_DEPARTMENT", dept.id,
        f"Excluiu setor {dept.name}",
    )
    db.delete(dept)
    db.commit()


@router.get("/directors")
def list_directors(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    directors = (
        db.query(User)
        .filter(User.role == UserRole.DIRECTOR, User.is_active.is_(True))
        .order_by(User.name)
        .all()
    )
    return [{"id": d.id, "name": d.name} for d in directors]


# ─── LGPD — Direitos dos Titulares ──────────────────────────────────────────

@router.post("/users/{user_id}/anonymize", status_code=status.HTTP_200_OK)
def anonymize_terminated_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """
    LGPD Art. 18 c/c Art. 16, I — Pseudonimizacao de colaborador desligado.

    Substitui dados identificaveis (nome, e-mail, senha) por valores
    irreversiveis. O ID, departamento e historico de aprovacoes SAO
    preservados para conformidade fiscal e trabalhista (prazo 5 anos CTN).
    Somente aplicavel a usuarios inativos.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador nao encontrado")

    if user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Impossivel anonimizar colaborador com contrato ativo. Desative a conta primeiro.",
        )

    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contas de administrador nao podem ser anonimizadas por este canal.",
        )

    # Pseudonimizacao irreversivel dos campos identificaveis
    suffix = str(uuid.uuid4())[:8]
    user.name = f"Colaborador Desligado {suffix}"
    user.email = f"purged-{uuid.uuid4()}@desligado.local"
    user.hashed_password = f"PURGED_PREVENT_LOGIN_{uuid.uuid4()}"  # login impossivel
    user.must_change_password = True
    user.manager_id = None  # desvincula da estrutura hierarquica

    # Auditoria da operacao (obrigatoria — LGPD Art. 37)
    _add_audit_log(
        db, request, current_user,
        "ANONYMIZE_USER",
        user_id,
        f"Pseudonimizacao LGPD aplicada ao usuario {user_id} (registro preservado para auditoria fiscal)",
    )
    db.commit()
    return {
        "status": "ok",
        "message": "Pseudonimizacao concluida. Dados de identificacao civil substituidos. "
                   "Historico fiscal e de aprovacoes preservado (conformidade Art. 16, I — LGPD).",
    }
