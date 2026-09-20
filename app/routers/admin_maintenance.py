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


@router.get("/maintenance/storage-reconciliation")
def storage_reconciliation(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role("ADMIN")),
):
    """CONF-05 (auditoria set/2026): identifica divergencias entre banco
    e armazenamento (R2). Retorna:
    - `db_refs`: numero de referencias `drive_file_id` no banco.
    - `orphan_objects`: objetos no bucket sem referencia no banco.
    - `broken_refs`: refs no banco cujo objeto nao existe no bucket.

    Read-only — nao apaga nada. Admin decide o que fazer com o resultado.
    Escaneia ate 5000 objetos por request pra nao travar.
    """
    from app.models import Invoice, InvoiceAttachment
    from app.services.drive_service import drive_service
    from app.config import settings

    # Todas as refs no banco
    inv_refs = {r for (r,) in db.query(Invoice.drive_file_id).filter(Invoice.drive_file_id.isnot(None)).all()}
    inv_print = {r for (r,) in db.query(Invoice.print_drive_file_id).filter(Invoice.print_drive_file_id.isnot(None)).all()}
    att_refs = {r for (r,) in db.query(InvoiceAttachment.drive_file_id).filter(InvoiceAttachment.drive_file_id.isnot(None)).all()}
    db_refs = inv_refs | inv_print | att_refs

    if drive_service.fallback_local or not settings.R2_BUCKET_NAME:
        return {
            "db_refs": len(db_refs),
            "orphan_objects": [],
            "broken_refs": [],
            "note": "R2 nao configurado — nao foi possivel listar bucket.",
        }

    # Lista ate 5000 objetos do bucket
    client = drive_service._client()
    remote_keys: set[str] = set()
    try:
        continuation = None
        for _ in range(5):  # 5 paginas * 1000 = 5000 objetos max
            kwargs = {"Bucket": settings.R2_BUCKET_NAME, "MaxKeys": 1000}
            if continuation:
                kwargs["ContinuationToken"] = continuation
            resp = client.list_objects_v2(**kwargs)
            for obj in resp.get("Contents", []):
                remote_keys.add(obj["Key"])
            if not resp.get("IsTruncated"):
                break
            continuation = resp.get("NextContinuationToken")
    except Exception as exc:  # noqa: BLE001
        return {
            "db_refs": len(db_refs),
            "orphan_objects": [],
            "broken_refs": [],
            "error": f"falha ao listar bucket: {exc}",
        }

    # Ignora refs "local:*" — sao do fallback DEV, nao pertencem ao R2
    remote_db_refs = {r for r in db_refs if not r.startswith("local:")}
    orphans = sorted(remote_keys - remote_db_refs)[:200]
    broken = sorted(remote_db_refs - remote_keys)[:200]
    return {
        "db_refs": len(db_refs),
        "remote_keys_scanned": len(remote_keys),
        "orphan_objects": orphans,
        "broken_refs": broken,
        "note": "Lista limitada a 200 exemplos por categoria.",
    }
