from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceStatus, User, UserRole

BR_TZ = ZoneInfo("America/Sao_Paulo")


def get_alerts(db: Session, user: User) -> dict:
    now = datetime.now(BR_TZ).date()
    limit_72h = now + timedelta(days=3)

    from app.services.invoice_service import _query_visible_invoices

    # Status que ainda fazem sentido alertar sobre vencimento/emissao.
    # Reprovadas NAO entram aqui — categoria propria 'rejected' abaixo.
    not_paid = [
        InvoiceStatus.RASCUNHO,
        InvoiceStatus.AGUARDANDO_GESTOR,
        InvoiceStatus.AGUARDANDO_DIRETOR,
        InvoiceStatus.APROVADO,
    ]

    overdue = (
        _query_visible_invoices(db, user)
        .filter(Invoice.due_date < now, Invoice.status.in_(not_paid))
        .order_by(Invoice.due_date.asc())
        .all()
    )

    due_72h = (
        _query_visible_invoices(db, user)
        .filter(
            Invoice.due_date >= now,
            Invoice.due_date <= limit_72h,
            Invoice.status.in_(not_paid),
        )
        .order_by(Invoice.due_date.asc())
        .all()
    )

    first_of_this_month = now.replace(day=1)
    old_emission = (
        _query_visible_invoices(db, user)
        .filter(
            Invoice.issue_date < first_of_this_month,
            Invoice.status.in_(not_paid),
        )
        .order_by(Invoice.issue_date.asc())
        .all()
    )

    # Notas reprovadas — categoria propria. So mostra para o CRIADOR delas
    # (aprovadores nao precisam de alerta de nota que ja saiu da fila deles).
    rejected = (
        _query_visible_invoices(db, user)
        .filter(
            Invoice.status.in_([InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR]),
            Invoice.created_by_id == user.id,
        )
        .order_by(Invoice.director_reviewed_at.desc().nullslast(), Invoice.manager_reviewed_at.desc())
        .all()
    )

    pending_review = []
    if user.role == UserRole.MANAGER:
        pending_review = (
            _query_visible_invoices(db, user)
            .filter(Invoice.status == InvoiceStatus.AGUARDANDO_GESTOR)
            .order_by(Invoice.submitted_at.asc())
            .all()
        )
    elif user.role == UserRole.DIRECTOR:
        pending_review = (
            _query_visible_invoices(db, user)
            .filter(Invoice.status == InvoiceStatus.AGUARDANDO_DIRETOR)
            .order_by(Invoice.submitted_at.asc())
            .all()
        )
    elif user.role == UserRole.FINANCE:
        pending_review = (
            _query_visible_invoices(db, user)
            .filter(Invoice.status == InvoiceStatus.APROVADO)
            .order_by(Invoice.director_reviewed_at.asc())
            .all()
        )

    def brief(inv: Invoice) -> dict:
        return {
            "id": inv.id,
            "invoice_number": inv.invoice_number,
            "amount": str(inv.amount),
            "due_date": str(inv.due_date),
            "issue_date": str(inv.issue_date),
            "status": inv.status.value,
            "created_by": inv.created_by.name if inv.created_by else None,
        }

    return {
        "overdue": [brief(i) for i in overdue],
        "due_72h": [brief(i) for i in due_72h],
        "old_emission": [brief(i) for i in old_emission],
        "rejected": [brief(i) for i in rejected],
        "pending_review": [brief(i) for i in pending_review],
        "summary": {
            "overdue_count": len(overdue),
            "due_72h_count": len(due_72h),
            "old_emission_count": len(old_emission),
            "rejected_count": len(rejected),
            "pending_review_count": len(pending_review),
            "total_alerts": len(overdue) + len(due_72h) + len(old_emission) + len(rejected),
        },
    }
