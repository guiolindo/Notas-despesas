"""Resolucao de diretores e gestores para roteamento de notas."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import User, UserRole


def _get_director(db: Session, director_id: str) -> User:
    director = db.query(User).filter(
        User.id == director_id,
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
    ).first()
    if not director:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diretor nao encontrado ou inativo",
        )
    if getattr(director, "unavailable_for_notes", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este diretor esta temporariamente indisponivel. Escolha outro.",
        )
    return director


def _get_manager_for_user(db: Session, user: User) -> User:
    """Retorna o gestor do setor do funcionario para receber uma nova nota.

    Exige que o gestor: (a) esteja ATIVO e (b) ainda tenha role MANAGER.
    Sem (b), funcionario com chefe promovido a DIRECTOR teria nota presa.

    Quando o gestor esta indisponivel (`unavailable_for_notes=True` — ex.
    ferias), tenta delegar pro substitute_manager_id. P1-9 da auditoria.
    """
    if not user.manager_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel identificar seu gestor responsavel. Contate o administrador.",
        )

    manager = (
        db.query(User)
        .filter(
            User.id == user.manager_id,
            User.is_active.is_(True),
            User.role == UserRole.MANAGER,
        )
        .first()
    )
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel identificar seu gestor responsavel. Contate o administrador.",
        )

    if not getattr(manager, "unavailable_for_notes", False):
        return manager

    # Gestor em ferias: tenta substituto designado por ele.
    sub_id = getattr(manager, "substitute_manager_id", None)
    if sub_id:
        sub = (
            db.query(User)
            .filter(
                User.id == sub_id,
                User.is_active.is_(True),
                User.role == UserRole.MANAGER,
            )
            .first()
        )
        if sub and not getattr(sub, "unavailable_for_notes", False):
            return sub

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Seu gestor esta temporariamente indisponivel e nao designou um "
            "substituto ativo. Aguarde o retorno ou contate o administrador."
        ),
    )


def _resolve_effective_director(db: Session, requested_director: User) -> User:
    """Se o diretor solicitado esta indisponivel e tem substituto ativo,
    retorna o substituto. Senao retorna o proprio."""
    if not getattr(requested_director, "unavailable_for_notes", False):
        return requested_director
    sub_id = getattr(requested_director, "substitute_director_id", None)
    if not sub_id:
        return requested_director
    sub = db.query(User).filter(User.id == sub_id).first()
    if sub and sub.role == UserRole.DIRECTOR and sub.is_active and not getattr(sub, "unavailable_for_notes", False):
        return sub
    return requested_director


def get_available_directors(db: Session, user: User) -> list[dict]:
    """Retorna lista de diretores ativos e DISPONIVEIS para receber notas.
    Diretores em 'ferias' sao omitidos."""
    directors = db.query(User).filter(
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
        User.unavailable_for_notes.is_(False),
    ).order_by(User.name).all()

    user_dept_id = user.department_id

    result = []
    for d in directors:
        dept_ids = {dept.id for dept in d.directed_departments}
        is_primary = user_dept_id is not None and user_dept_id in dept_ids
        dept_names = [dept.name for dept in d.directed_departments]
        result.append({
            "id": d.id,
            "name": d.name,
            "email": d.email,
            "is_primary": is_primary,
            "departments": dept_names,
        })

    # Ordenar: primário primeiro
    result.sort(key=lambda x: (not x["is_primary"], x["name"]))
    return result
