"""Endpoints admin de setores (departments) + listagem de diretores."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, Department, User, UserRole
from app.security.dependencies import require_role

from app.routers.admin_shared import (
    DepartmentRequest,
    add_audit_log,
    client_ip,
    client_port,
    now_utc,
)


router = APIRouter()


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
        ip_address=client_ip(request), source_port=client_port(request),
        http_method=request.method, timestamp=now_utc(), success=True,
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
        ip_address=client_ip(request), source_port=client_port(request),
        http_method=request.method, timestamp=now_utc(), success=True,
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
    add_audit_log(
        db, request, current_user,
        "DELETE_DEPARTMENT", dept.id,
        f"Excluiu setor {dept.name}",
        resource_type="Department",
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
