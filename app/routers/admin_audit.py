"""Endpoints admin de auditoria — listagem paginada + verify-chain."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AuditLog, User
from app.security.dependencies import require_role

from app.routers.admin_shared import utc_iso


router = APIRouter()


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
                "timestamp": utc_iso(log.timestamp),
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


@router.get("/audit-logs/verify-chain")
def verify_audit_chain(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """Recalcula o hash de cada audit_log da mais antiga para a mais recente
    e compara com o valor salvo. Qualquer divergencia indica edicao
    retroativa direta no banco — defesa contra admin com acesso ao SQL.

    Retorna {ok, total, first_broken_id, first_broken_at, message}.
    """
    from app.models.audit_logs import GENESIS_HASH, compute_row_hash

    rows = (
        db.query(AuditLog)
        .order_by(AuditLog.timestamp.asc(), AuditLog.id.asc())
        .all()
    )
    prev = GENESIS_HASH
    broken = None
    for row in rows:
        expected = compute_row_hash(prev, row)
        if row.row_hash and row.row_hash != expected:
            broken = row
            break
        # Se row_hash for None (linhas antigas pre-feature), nao quebra
        # a verificacao — apenas avanca a cadeia computando o hash.
        prev = row.row_hash or expected
    if broken:
        return {
            "ok": False,
            "total": len(rows),
            "first_broken_id": broken.id,
            "first_broken_at": broken.timestamp.isoformat() if broken.timestamp else None,
            "message": (
                "Cadeia de auditoria quebrada. Edicao retroativa detectada na "
                f"linha {broken.id}. Investigar acesso direto ao banco."
            ),
        }
    return {
        "ok": True,
        "total": len(rows),
        "first_broken_id": None,
        "first_broken_at": None,
        "message": "Cadeia integra.",
    }
