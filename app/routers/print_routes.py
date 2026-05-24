import io
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.main import templates
from app.models import (
    ApprovalAction,
    ApprovalHistory,
    AuditLog,
    Invoice,
    InvoiceStatus,
    User,
    UserRole,
)
from app.security.dependencies import get_current_user, require_role
from app.security.hashing import pseudonymize_ip
from app.services.pdf_service import generate_print_pdf, invoice_hash


router = APIRouter()


def _invoice_with_relations(db: Session, invoice_id: str) -> Invoice | None:
    return (
        db.query(Invoice)
        .options(
            selectinload(Invoice.created_by),
            selectinload(Invoice.manager),
            selectinload(Invoice.director),
            selectinload(Invoice.finance),
            selectinload(Invoice.approval_history).selectinload(ApprovalHistory.user),
        )
        .filter(Invoice.id == invoice_id)
        .first()
    )


@router.get("/api/invoices/{invoice_id}/print")
def print_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FINANCE.value, UserRole.ADMIN.value)),
):
    invoice = _invoice_with_relations(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota nao encontrada")
    if invoice.status not in {InvoiceStatus.APROVADO, InvoiceStatus.PAGO}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas notas aprovadas ou pagas podem ser impressas",
        )

    pdf_bytes = generate_print_pdf(invoice, str(request.base_url))
    now = datetime.now(timezone.utc)
    _ip = pseudonymize_ip(request.client.host if request.client else None)
    _port = request.client.port if request.client else None

    # Reimpressoes NAO geram log nem entrada no historico — apenas o evento
    # de lancamento (1a impressao) e auditado, evitando spam de registros.
    is_first_print = invoice.printed_at is None
    if is_first_print:
        db.add(
            ApprovalHistory(
                id=str(uuid.uuid4()),
                invoice_id=invoice.id,
                user_id=current_user.id,
                action=ApprovalAction.PRINTED,
                timestamp=now,
                ip_address=_ip,
                source_port=_port,
            )
        )
        db.add(
            AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                action="PRINT_INVOICE",
                resource_type="INVOICE",
                resource_id=invoice.id,
                ip_address=_ip,
                source_port=_port,
                http_method=request.method,
                user_agent=request.headers.get("user-agent"),
                timestamp=now,
                success=True,
            )
        )
    # printed_at sempre atualiza para refletir a impressao mais recente
    invoice.printed_at = now
    invoice.printed_by_id = current_user.id

    # Finalizacao automatica: impressao no Financeiro equivale a lancamento
    # da nota (o sistema nao executa pagamento real). Tira a nota da fila
    # operacional sem clique extra. Reimpressoes continuam permitidas porque
    # o endpoint aceita status APROVADO ou PAGO (= LANCADO internamente).
    if invoice.status == InvoiceStatus.APROVADO:
        invoice.status = InvoiceStatus.PAGO
        invoice.paid_at = now
        invoice.finance_id = current_user.id
        db.add(
            ApprovalHistory(
                id=str(uuid.uuid4()),
                invoice_id=invoice.id,
                user_id=current_user.id,
                action=ApprovalAction.MARKED_PAID,
                comment="Lancada automaticamente apos impressao",
                timestamp=now,
                ip_address=_ip,
                source_port=_port,
            )
        )
        db.add(
            AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                action="AUTO_MARK_PAID_ON_PRINT",
                resource_type="INVOICE",
                resource_id=invoice.id,
                ip_address=_ip,
                source_port=_port,
                http_method=request.method,
                user_agent=request.headers.get("user-agent"),
                timestamp=now,
                success=True,
            )
        )

    db.commit()

    safe_number = invoice.invoice_number.replace("/", "-").replace("\\", "-")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="nota_{safe_number}_comprovante.pdf"'},
    )


@router.get("/verify/{invoice_id}", response_class=HTMLResponse)
def verify_invoice(invoice_id: str, request: Request, db: Session = Depends(get_db)):
    invoice = _invoice_with_relations(db, invoice_id)
    context = {
        "request": request,
        "invoice": invoice,
        "auth_hash": None,
        "director_reviewed_at_br": None,
        "amount_formatted": "-",
    }
    if invoice:
        context["auth_hash"] = invoice_hash(invoice)
        # Converte UTC -> Brasilia para exibicao
        if invoice.director_reviewed_at:
            from datetime import timezone as _tz, timedelta as _td
            dt = invoice.director_reviewed_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_tz.utc)
            br = dt.astimezone(_tz(_td(hours=-3)))
            context["director_reviewed_at_br"] = br.strftime("%d/%m/%Y %H:%M")
        # Formatacao monetaria pt-BR (1.234,56)
        try:
            v = float(invoice.amount)
            context["amount_formatted"] = f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:  # noqa: BLE001
            context["amount_formatted"] = f"R$ {invoice.amount}"
    return templates.TemplateResponse(request, "verify.html", context)
