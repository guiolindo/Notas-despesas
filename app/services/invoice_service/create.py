"""Criacao + edicao de notas (sem transicoes FSM — essas vivem em fsm.py).
Inclui soft-check de duplicidade P1-3."""
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceStatus, ApprovalAction, User

from app.services.invoice_service._shared import (
    _add_audit,
    _add_history,
    _now,
    _sanitize_text,
)
from app.services.invoice_service.attachments import _add_attachments
from app.services.invoice_service.queries import _get_invoice


def _check_duplicate_invoice_number(
    db: Session,
    *,
    user_id: str,
    supplier_document: str | None,
    invoice_number: str,
    exclude_id: str | None = None,
) -> Invoice | None:
    """Retorna a primeira nota ATIVA com mesmo numero, ou None.

    P1-3 da auditoria: invoice_number nao tem UNIQUE no DB porque, no Brasil,
    fornecedores diferentes podem usar a mesma numeracao. Considera-se
    duplicada quando coincide:
      - (created_by_id, invoice_number), OU
      - (supplier_document, invoice_number) — quando supplier_document existe.
    Notas REPROVADO ou RASCUNHO antigas nao contam.
    """
    from sqlalchemy import or_

    if not invoice_number:
        return None
    candidates = db.query(Invoice).filter(
        Invoice.invoice_number == invoice_number,
        Invoice.status.notin_({
            InvoiceStatus.RASCUNHO,
            InvoiceStatus.REPROVADO_GESTOR,
            InvoiceStatus.REPROVADO_DIRETOR,
        }),
    )
    if exclude_id:
        candidates = candidates.filter(Invoice.id != exclude_id)
    same_user = Invoice.created_by_id == user_id
    if supplier_document:
        candidates = candidates.filter(
            or_(same_user, Invoice.supplier_document == supplier_document)
        )
    else:
        candidates = candidates.filter(same_user)
    return candidates.order_by(Invoice.created_at.desc()).first()


def _raise_duplicate_invoice_number(existing: Invoice) -> None:
    """Resposta 409 padronizada quando duplicidade e detectada."""
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "DUPLICATE_INVOICE_NUMBER",
            "message": (
                f"Ja existe uma nota com o numero '{existing.invoice_number}' "
                f"(status: {existing.status.value}). "
                "Reenvie marcando 'confirmar duplicidade' se realmente for outra nota."
            ),
            "existing_invoice_id": existing.id,
            "existing_status": existing.status.value,
        },
    )


def create_invoice(
    db: Session,
    data,
    user: User,
    files: list[tuple[bytes, str]] | None = None,
    ip: str | None = None,
    port: int | None = None,
    submit_now: bool = False,
    director_id: str | None = None,
) -> Invoice:
    """Cria nota com lista de arquivos (1-5 anexos PDF)."""
    from app.services.document_service import detect_document_type, strip_non_digits
    from app.services.invoice_service.fsm import _do_submit

    supplier_doc = strip_non_digits(data.supplier_document)
    # Soft-check de duplicidade so quando o submit ja vai pra cima.
    if submit_now and not getattr(data, "confirm_duplicate", False):
        existing = _check_duplicate_invoice_number(
            db,
            user_id=user.id,
            supplier_document=supplier_doc,
            invoice_number=_sanitize_text(data.invoice_number),
        )
        if existing:
            _raise_duplicate_invoice_number(existing)
    invoice = Invoice(
        id=str(uuid.uuid4()),
        invoice_number=_sanitize_text(data.invoice_number),
        issue_date=data.issue_date,
        due_date=data.due_date,
        description=_sanitize_text(data.description),
        bank_details=_sanitize_text(data.bank_details),
        amount=data.amount,
        status=InvoiceStatus.RASCUNHO,
        created_by_id=user.id,
        created_at=_now(),
        supplier_document=supplier_doc,
        supplier_document_type=detect_document_type(supplier_doc),
        supplier_name=_sanitize_text(data.supplier_name),
        supplier_legal_name=_sanitize_text(data.supplier_legal_name),
    )
    db.add(invoice)
    db.flush()  # garante invoice.id antes de criar attachments
    if files:
        _add_attachments(db, invoice, files, uploaded_by_id=user.id)
    _add_history(db, invoice.id, user.id, ApprovalAction.CREATED, ip=ip, port=port)
    _add_audit(db, user.id, "CREATE_INVOICE", invoice.id, ip=ip, port=port, http_method="POST")

    if submit_now:
        _do_submit(db, invoice, user, director_id, ip, port)

    db.commit()
    return _get_invoice(db, invoice.id)


def update_invoice(
    db: Session,
    invoice_id: str,
    data,
    user: User,
    new_files: list[tuple[bytes, str]] | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status not in {
        InvoiceStatus.RASCUNHO,
        InvoiceStatus.REPROVADO_GESTOR,
        InvoiceStatus.REPROVADO_DIRETOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota nao pode ser alterada neste status",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if value is not None and isinstance(value, str):
            value = _sanitize_text(value)
        setattr(invoice, field, value)
    if invoice.due_date and invoice.issue_date and invoice.due_date < invoice.issue_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Vencimento deve ser igual ou posterior a data de emissao",
        )

    if new_files:
        _add_attachments(db, invoice, new_files, uploaded_by_id=user.id)
    _add_audit(db, user.id, "UPDATE_INVOICE", invoice.id, ip=ip, port=port, http_method="PATCH")
    db.commit()
    return _get_invoice(db, invoice.id)
