"""Limpeza de notas reprovadas com mais de N dias."""
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceStatus
from app.services.drive_service import drive_service

from app.services.invoice_service._shared import (
    REJECTED_AUTO_DELETE_DAYS,
    _add_audit,
)
from app.services.invoice_service.queries import _invoice_options


def purge_old_rejected_invoices(db: Session) -> int:
    """Apaga notas reprovadas ha mais de REJECTED_AUTO_DELETE_DAYS dias.

    Roda no startup do app (idempotente — se ja apagado, no-op).
    Apaga arquivos no R2 + linha no banco (cascade limpa anexos+historico).
    Retorna quantidade apagada.

    Notas APROVADAS/LANCADAS NUNCA sao apagadas — obrigacao fiscal CTN 5 anos.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=REJECTED_AUTO_DELETE_DAYS)
    cutoff_naive = cutoff.replace(tzinfo=None)

    old_rejected = (
        db.query(Invoice)
        .options(*_invoice_options())
        .filter(
            Invoice.status.in_([InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR]),
            ((Invoice.director_reviewed_at != None) & (Invoice.director_reviewed_at < cutoff_naive))
            | ((Invoice.director_reviewed_at == None) & (Invoice.manager_reviewed_at < cutoff_naive)),
        )
        .all()
    )
    count = 0
    for inv in old_rejected:
        for att in list(inv.attachments):
            if att.drive_file_id:
                try:
                    drive_service.delete_file(att.drive_file_id)
                except Exception:  # noqa: BLE001
                    pass
        _add_audit(
            db, None, "AUTO_DELETE_REJECTED", inv.id,
            detail=f"Removida automaticamente apos {REJECTED_AUTO_DELETE_DAYS} dias de reprovacao",
        )
        db.delete(inv)
        count += 1
    if count:
        db.commit()
    return count
