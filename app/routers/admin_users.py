"""Endpoints admin de usuarios — CRUD, reset/unlock, anonymize."""
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.security.dependencies import require_role
from app.security.hashing import hash_password

from app.routers.admin_shared import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserUpdateRequest,
    active_admins_except,
    add_audit_log,
    ensure_department_exists,
    ensure_manager_exists,
    is_anonymized,
    notify_directors_peer,
    now_utc,
    user_payload,
    validate_user_structure,
)


router = APIRouter()


@router.get("/users")
def list_users(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    users = db.query(User).order_by(User.name).all()
    return [user_payload(user) for user in users]


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
    ensure_manager_exists(db, manager_id)
    ensure_department_exists(db, body.department_id)
    validate_user_structure(
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
    add_audit_log(
        db, request, current_user,
        "CREATE_USER", new_user.id,
        f"Criou usuario {new_user.email} com role {new_user.role.value}",
    )
    db.commit()
    db.refresh(new_user)
    # Notificacao peer: criacao de diretor avisa todos os outros diretores
    if new_user.role == UserRole.DIRECTOR:
        notify_directors_peer(
            db, current_user, "Criacao de novo diretor", new_user, exclude_target=True,
        )
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
    return user_payload(user)


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

    # Usuario anonimizado (LGPD) e final — nao reativa, nao re-edita identidade.
    if is_anonymized(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta conta ja foi encerrada — nao pode mais ser reativada nem editada. "
                   "Cadastre um novo usuario se a pessoa retornar.",
        )

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

    # ─── Janela de 24h para desativacao de diretor ───
    # Defesa contra cenario de admin malicioso: em vez de executar
    # imediatamente, cria PendingAdminAction.
    if (
        user.role == UserRole.DIRECTOR
        and user.is_active is True
        and body.is_active is False
    ):
        from app.models import (
            GRACE_PERIOD_HOURS,
            PendingActionStatus,
            PendingActionType,
            PendingAdminAction,
        )
        existing = (
            db.query(PendingAdminAction)
            .filter(
                PendingAdminAction.target_user_id == user.id,
                PendingAdminAction.action_type == PendingActionType.DEACTIVATE_DIRECTOR,
                PendingAdminAction.status == PendingActionStatus.PENDING,
            )
            .first()
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Ja existe uma solicitacao de desativacao pendente para este diretor.",
            )
        now = now_utc()
        pa = PendingAdminAction(
            id=str(uuid.uuid4()),
            action_type=PendingActionType.DEACTIVATE_DIRECTOR,
            target_user_id=user.id,
            requested_by_id=current_user.id,
            requested_at=now,
            effective_at=now + timedelta(hours=GRACE_PERIOD_HOURS),
            status=PendingActionStatus.PENDING,
            reason=None,
        )
        db.add(pa)
        add_audit_log(
            db, request, current_user,
            "REQUEST_DEACTIVATE_DIRECTOR", user.id,
            f"Solicitou desativacao do diretor {user.email}. Efetiva em {GRACE_PERIOD_HOURS}h se nao cancelada.",
        )
        notify_directors_peer(
            db, current_user, "Solicitacao de desativacao de diretor (24h)", user,
            exclude_target=False,
        )
        db.commit()
        return {
            "message": "Desativacao agendada para daqui a 24h. O diretor afetado e os "
                       "demais foram avisados e podem cancelar dentro da janela.",
            "pending_action_id": pa.id,
        }

    removing_last_admin_role = body.role is not None and body.role != UserRole.ADMIN and user.role == UserRole.ADMIN
    deactivating_last_admin = body.is_active is False and user.role == UserRole.ADMIN
    if (removing_last_admin_role or deactivating_last_admin) and active_admins_except(db, user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao e possivel remover o ultimo ADMIN do sistema",
        )

    # Snapshot pre-update para detectar mudancas que disparam notificacao peer
    pre_role = user.role
    pre_active = user.is_active

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
    if final_role == UserRole.EMPLOYEE:
        if body.manager_id is not None:
            final_manager_id = body.manager_id.strip() or None
        else:
            final_manager_id = user.manager_id
    else:
        final_manager_id = None

    ensure_department_exists(db, final_dept_id)
    ensure_manager_exists(db, final_manager_id)
    validate_user_structure(final_role, final_dept_id, final_manager_id, final_submit_direct)

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

    add_audit_log(
        db, request, current_user,
        "UPDATE_USER", user.id,
        f"Editou campos: {', '.join(changes) or 'nenhum'} do usuario {user.email}",
    )
    db.commit()

    # Notificacoes peer (apos commit pra refletir estado real)
    became_director = pre_role != UserRole.DIRECTOR and user.role == UserRole.DIRECTOR
    deactivated_director = pre_role == UserRole.DIRECTOR and pre_active and not user.is_active
    if became_director:
        notify_directors_peer(
            db, current_user, "Promocao para diretor", user, exclude_target=True,
        )
    elif deactivated_director:
        notify_directors_peer(
            db, current_user, "Desativacao de diretor", user, exclude_target=False,
        )
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

    if is_anonymized(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta conta foi encerrada — o login esta permanentemente bloqueado.",
        )

    notify_director_reset = (
        user.role == UserRole.DIRECTOR
        and user.id != current_user.id
        and user.is_active
    )

    # PROTECAO: nenhum admin pode resetar senha de outro admin (evita sequestro).
    if user.role == UserRole.ADMIN and user.id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Nao e possivel redefinir a senha de outro administrador. "
                "O proprio admin deve usar 'Trocar senha' apos login."
            ),
        )

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
    user.password_changed_at = datetime.now(timezone.utc)
    user.must_change_password = True
    user.login_attempts = 0
    user.blocked_until = None
    add_audit_log(
        db, request, current_user,
        "RESET_PASSWORD", user.id,
        f"Redefiniu senha do usuario {user.email}",
    )
    db.commit()
    if notify_director_reset:
        notify_directors_peer(
            db, current_user, "Redefinicao de senha de diretor", user,
            exclude_target=False,
        )
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
    add_audit_log(
        db, request, current_user,
        "UNLOCK_USER", user.id,
        f"Desbloqueou usuario {user.email}",
    )
    db.commit()
    return {"message": "Usuario desbloqueado com sucesso"}


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


@router.post("/users/{user_id}/anonymize", status_code=status.HTTP_200_OK)
def anonymize_terminated_user(
    user_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """LGPD Art. 18 c/c Art. 16, I — Pseudonimizacao de colaborador desligado.

    Substitui dados identificaveis (nome, e-mail, senha) por valores
    irreversiveis. O ID, departamento e historico de aprovacoes SAO
    preservados para conformidade fiscal e trabalhista (prazo 5 anos CTN).
    Somente aplicavel a usuarios inativos.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Colaborador nao encontrado")

    if is_anonymized(user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario ja foi anonimizado anteriormente.",
        )

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

    # Snapshot pre-mudanca pra notificacao peer com nome real
    was_director = user.role == UserRole.DIRECTOR
    target_snapshot = User(
        id=user.id, name=user.name, email=user.email, role=user.role,
    )

    # Pseudonimizacao irreversivel dos campos identificaveis
    suffix = str(uuid.uuid4())[:8]
    user.name = f"Colaborador Desligado {suffix}"
    user.email = f"purged-{uuid.uuid4()}@desligado.local"
    user.hashed_password = f"PURGED_PREVENT_LOGIN_{uuid.uuid4()}"  # login impossivel
    user.must_change_password = True
    user.manager_id = None

    add_audit_log(
        db, request, current_user,
        "ANONYMIZE_USER", user_id,
        f"Pseudonimizacao LGPD aplicada ao usuario {user_id} (registro preservado para auditoria fiscal)",
    )
    db.commit()

    if was_director:
        notify_directors_peer(
            db, current_user, "Encerramento de conta de diretor", target_snapshot,
            exclude_target=True,
        )

    return {
        "status": "ok",
        "message": "Pseudonimizacao concluida. Dados de identificacao civil substituidos. "
                   "Historico fiscal e de aprovacoes preservado (conformidade Art. 16, I — LGPD).",
    }
