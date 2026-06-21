"""Constantes + helpers (notificacoes, audit, history) compartilhados
entre os sub-modulos do invoice_service.

Split jun/2026 (Fase 4 do plan-refactor-master).
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    ApprovalAction,
    ApprovalHistory,
    AuditLog,
    Invoice,
    InvoiceStatus,
    User,
    UserRole,
)
from app.services import email_service


MAX_ATTACHMENTS_PER_INVOICE = 5
MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB
REJECTED_AUTO_DELETE_DAYS = 90


FSM_TRANSITIONS = {
    "submit_to_manager": (InvoiceStatus.RASCUNHO, InvoiceStatus.AGUARDANDO_GESTOR),
    "submit_to_director": (InvoiceStatus.RASCUNHO, InvoiceStatus.AGUARDANDO_DIRETOR),
    "cancel": (None, InvoiceStatus.RASCUNHO),  # múltiplos status de origem
    "manager_approve": (InvoiceStatus.AGUARDANDO_GESTOR, InvoiceStatus.AGUARDANDO_DIRETOR),
    "manager_reject": (InvoiceStatus.AGUARDANDO_GESTOR, InvoiceStatus.REPROVADO_GESTOR),
    "director_approve": (InvoiceStatus.AGUARDANDO_DIRETOR, InvoiceStatus.APROVADO),
    "director_reject": (InvoiceStatus.AGUARDANDO_DIRETOR, InvoiceStatus.REPROVADO_DIRETOR),
    "mark_paid": (InvoiceStatus.APROVADO, InvoiceStatus.PAGO),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _sanitize_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().replace("\x00", "")


def _safe_currency(value) -> str:
    try:
        return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:  # noqa: BLE001
        return str(value)


def _notify_approver(db: Session, recipient: User, invoice: Invoice) -> None:
    """Avisa por email que ha nota nova pra aprovar. Async (nao bloqueia request)."""
    if not recipient or not recipient.email or not recipient.is_active:
        return
    subject, html, text = email_service.template_new_invoice_for_approver(
        approver_name=recipient.name,
        creator_name=invoice.created_by.name if invoice.created_by else "Sistema",
        invoice_number=invoice.invoice_number,
        amount=_safe_currency(invoice.amount),
        public_url=f"/invoices/{invoice.id}",
    )
    email_service.send_email_async(recipient.email, subject, html, text)


def _notify_rejection(db: Session, invoice: Invoice, rejected_by: User, reason: str | None) -> None:
    creator = invoice.created_by
    if not creator or not creator.email or not creator.is_active:
        return
    subject, html, text = email_service.template_invoice_rejected(
        creator_name=creator.name,
        invoice_number=invoice.invoice_number,
        rejected_by=rejected_by.name if rejected_by else "Sistema",
        reason=reason or "",
        public_url=f"/invoices/{invoice.id}",
    )
    email_service.send_email_async(creator.email, subject, html, text)


def _notify_finance_team(db: Session, invoice: Invoice) -> None:
    """Quando diretor aprova, avisa TODOS do financeiro."""
    finance_users = (
        db.query(User)
        .filter(User.role == UserRole.FINANCE, User.is_active.is_(True))
        .all()
    )
    for fu in finance_users:
        if not fu.email:
            continue
        subject, html, text = email_service.template_new_invoice_for_approver(
            approver_name=fu.name,
            creator_name=invoice.created_by.name if invoice.created_by else "Sistema",
            invoice_number=invoice.invoice_number,
            amount=_safe_currency(invoice.amount),
            public_url=f"/invoices/{invoice.id}",
        )
        email_service.send_email_async(fu.email, subject, html, text)


def _add_history(
    db: Session,
    invoice_id: str,
    user_id: str,
    action: ApprovalAction,
    comment: str | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> None:
    db.add(
        ApprovalHistory(
            id=str(uuid.uuid4()),
            invoice_id=invoice_id,
            user_id=user_id,
            action=action,
            comment=_sanitize_text(comment),
            ip_address=ip,
            source_port=port,
            timestamp=_now(),
        )
    )


def _add_audit(
    db: Session,
    user_id: str | None,
    action: str,
    resource_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
    http_method: str | None = None,
    detail: str | None = None,
) -> None:
    db.add(
        AuditLog(
            id=str(uuid.uuid4()),
            user_id=user_id,
            action=action,
            resource_type="INVOICE",
            resource_id=resource_id,
            ip_address=ip,
            source_port=port,
            http_method=http_method,
            timestamp=_now(),
            success=True,
            detail=detail,
        )
    )
