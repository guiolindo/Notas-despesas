from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceStatus, User, UserRole

BR_TZ = ZoneInfo("America/Sao_Paulo")

_NOT_PAID_STATUS = [
    InvoiceStatus.RASCUNHO,
    InvoiceStatus.AGUARDANDO_GESTOR,
    InvoiceStatus.AGUARDANDO_DIRETOR,
    InvoiceStatus.APROVADO,
]


def get_alerts_summary(db: Session, user: User) -> dict:
    """DB-05 (auditoria set/2026): antes, o badge de menu do shell chamava
    /alerts/ que retornava 5 listas completas (sem LIMIT) com eager loading
    do grafo inteiro. Um diretor com muitas notas transferia MB por
    navegacao. Este endpoint retorna apenas COUNTs — 5 queries triviais,
    sem materializacao de entidade.
    """
    from app.services.invoice_service import _query_visible_invoices

    today = datetime.now(BR_TZ).date()
    limit_72h = today + timedelta(days=3)
    first_of_this_month = today.replace(day=1)

    def _count(q) -> int:
        return int(q.with_entities(func.count(Invoice.id)).order_by(None).scalar() or 0)

    base = _query_visible_invoices(db, user, light=True)

    overdue = _count(
        base.filter(Invoice.due_date < today, Invoice.status.in_(_NOT_PAID_STATUS))
    )
    due_72h = _count(
        base.filter(
            Invoice.due_date >= today,
            Invoice.due_date <= limit_72h,
            Invoice.status.in_(_NOT_PAID_STATUS),
        )
    )
    old_emission = _count(
        base.filter(
            Invoice.issue_date < first_of_this_month,
            Invoice.status.in_(_NOT_PAID_STATUS),
        )
    )
    rejected = _count(
        base.filter(
            Invoice.status.in_(
                [InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR]
            ),
            Invoice.created_by_id == user.id,
        )
    )

    pending_review = 0
    if user.role == UserRole.MANAGER:
        pending_review = _count(
            base.filter(Invoice.status == InvoiceStatus.AGUARDANDO_GESTOR)
        )
    elif user.role == UserRole.DIRECTOR:
        pending_review = _count(
            base.filter(Invoice.status == InvoiceStatus.AGUARDANDO_DIRETOR)
        )
    elif user.role == UserRole.FINANCE:
        pending_review = _count(
            base.filter(Invoice.status == InvoiceStatus.APROVADO)
        )

    return {
        "overdue_count": overdue,
        "due_72h_count": due_72h,
        "old_emission_count": old_emission,
        "rejected_count": rejected,
        "pending_review_count": pending_review,
        "total_alerts": overdue + due_72h + old_emission + rejected,
    }


def get_alerts(db: Session, user: User) -> dict:
    now = datetime.now(BR_TZ).date()
    limit_72h = now + timedelta(days=3)

    from app.services.invoice_service import _query_visible_invoices

    # DB-05: teto duro em cada bucket. Antes era .all() sem LIMIT — diretor
    # com muitas notas atrasadas recebia payload proporcional a base
    # historica a cada request. UI so precisa dos primeiros itens (o resto
    # ve pela pagina /alerts com paginacao completa quando ela existir).
    _BUCKET_LIMIT = 50

    not_paid = _NOT_PAID_STATUS

    overdue = (
        _query_visible_invoices(db, user, light=True)
        .filter(Invoice.due_date < now, Invoice.status.in_(not_paid))
        .order_by(Invoice.due_date.asc())
        .limit(_BUCKET_LIMIT)
        .all()
    )

    due_72h = (
        _query_visible_invoices(db, user, light=True)
        .filter(
            Invoice.due_date >= now,
            Invoice.due_date <= limit_72h,
            Invoice.status.in_(not_paid),
        )
        .order_by(Invoice.due_date.asc())
        .limit(_BUCKET_LIMIT)
        .all()
    )

    first_of_this_month = now.replace(day=1)
    old_emission = (
        _query_visible_invoices(db, user, light=True)
        .filter(
            Invoice.issue_date < first_of_this_month,
            Invoice.status.in_(not_paid),
        )
        .order_by(Invoice.issue_date.asc())
        .limit(_BUCKET_LIMIT)
        .all()
    )

    rejected = (
        _query_visible_invoices(db, user, light=True)
        .filter(
            Invoice.status.in_([InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR]),
            Invoice.created_by_id == user.id,
        )
        .order_by(Invoice.director_reviewed_at.desc().nullslast(), Invoice.manager_reviewed_at.desc())
        .limit(_BUCKET_LIMIT)
        .all()
    )

    pending_review = []
    if user.role == UserRole.MANAGER:
        pending_review = (
            _query_visible_invoices(db, user, light=True)
            .filter(Invoice.status == InvoiceStatus.AGUARDANDO_GESTOR)
            .order_by(Invoice.submitted_at.asc())
            .limit(_BUCKET_LIMIT)
            .all()
        )
    elif user.role == UserRole.DIRECTOR:
        pending_review = (
            _query_visible_invoices(db, user, light=True)
            .filter(Invoice.status == InvoiceStatus.AGUARDANDO_DIRETOR)
            .order_by(Invoice.submitted_at.asc())
            .limit(_BUCKET_LIMIT)
            .all()
        )
    elif user.role == UserRole.FINANCE:
        pending_review = (
            _query_visible_invoices(db, user, light=True)
            .filter(Invoice.status == InvoiceStatus.APROVADO)
            .order_by(Invoice.director_reviewed_at.asc())
            .limit(_BUCKET_LIMIT)
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
