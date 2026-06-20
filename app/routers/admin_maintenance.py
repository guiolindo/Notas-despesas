"""Endpoints admin de manutencao — purge de notas reprovadas."""
from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import require_role

from app.routers.admin_shared import add_audit_log


router = APIRouter()


@router.post("/maintenance/purge-rejected")
def purge_rejected_invoices(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """Roda purge manual de notas reprovadas ha mais de 90 dias.
    Tambem roda automaticamente no startup do app — endpoint util pra
    forcar antes de relatorios ou apos limpar muitas notas de teste."""
    from app.services.invoice_service import purge_old_rejected_invoices
    count = purge_old_rejected_invoices(db)
    add_audit_log(
        db, request, current_user,
        "PURGE_REJECTED", "invoices",
        f"Purge manual: {count} nota(s) reprovada(s) >90 dias removida(s)",
        resource_type="Invoice",
    )
    db.commit()
    return {"removed": count, "message": f"{count} nota(s) reprovada(s) ha mais de 90 dias foram removidas."}
