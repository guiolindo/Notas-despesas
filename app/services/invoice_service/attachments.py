"""Anexos: validacao de limites, upload criptografado, download, delete."""
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import Invoice, InvoiceAttachment, User
from app.services.drive_service import drive_service

from app.services.invoice_service._shared import (
    MAX_ATTACHMENTS_PER_INVOICE,
    MAX_TOTAL_ATTACHMENT_BYTES,
    _add_audit,
)
from app.services.invoice_service.queries import get_invoice_or_403


def _sanitize_attachment_name(name: str | None) -> str:
    """Sanitiza nome do arquivo preservando legibilidade.
    Remove path traversal, caracteres especiais e limita tamanho.
    """
    if not name:
        return "anexo.pdf"
    from pathlib import Path
    import re
    base = Path(name).name
    safe = re.sub(r"[^\w\s\.\-\(\)]", "_", base)[:120]
    if not safe.lower().endswith(".pdf"):
        safe = safe + ".pdf"
    return safe or "anexo.pdf"


def _validate_attachment_limits(
    db: Session, invoice: Invoice, new_files: list[tuple[bytes, str]]
) -> None:
    """Checa que o conjunto (existentes + novos) cabe nos limites."""
    existing = invoice.attachments or []
    total_count = len(existing) + len(new_files)
    if total_count > MAX_ATTACHMENTS_PER_INVOICE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximo de {MAX_ATTACHMENTS_PER_INVOICE} arquivos por nota.",
        )
    existing_size = sum((a.size_bytes or 0) for a in existing)
    new_size = sum(len(b) for b, _ in new_files)
    if existing_size + new_size > MAX_TOTAL_ATTACHMENT_BYTES:
        mb_max = MAX_TOTAL_ATTACHMENT_BYTES / (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tamanho total dos anexos excede {mb_max:.0f} MB.",
        )


def _add_attachments(
    db: Session,
    invoice: Invoice,
    files: list[tuple[bytes, str]],
    uploaded_by_id: str | None = None,
) -> None:
    """Adiciona N arquivos como anexos da nota. Cada um eh criptografado
    individualmente. Falha de upload de QUALQUER um aborta a operacao."""
    if not files:
        return
    _validate_attachment_limits(db, invoice, files)
    for file_bytes, filename in files:
        if not file_bytes:
            continue
        safe_name = _sanitize_attachment_name(filename)
        drive_file_id, encrypted_key = drive_service.upload_encrypted_file(
            file_bytes, safe_name,
        )
        db.add(InvoiceAttachment(
            invoice_id=invoice.id,
            drive_file_id=drive_file_id,
            drive_file_name=safe_name,
            encryption_key_enc=encrypted_key,
            size_bytes=len(file_bytes),
            uploaded_by_id=uploaded_by_id,
        ))


def _delete_attachment_record(db: Session, attachment: InvoiceAttachment) -> None:
    """Apaga um anexo individual — arquivo no R2 + linha no banco."""
    if attachment.drive_file_id:
        try:
            drive_service.delete_file(attachment.drive_file_id)
        except Exception:  # noqa: BLE001
            pass
    db.delete(attachment)


def get_attachment(
    db: Session,
    invoice_id: str,
    user: User,
    attachment_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> tuple[bytes, str]:
    """Baixa um anexo especifico (se attachment_id passado) ou o primeiro
    anexo da nota. Retorna (bytes do PDF descriptografado, nome do arquivo)."""
    invoice = get_invoice_or_403(db, invoice_id, user)
    if not invoice.attachments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum anexo encontrado")
    if attachment_id:
        att = next((a for a in invoice.attachments if a.id == attachment_id), None)
        if not att:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anexo nao encontrado")
    else:
        att = invoice.attachments[0]
    _add_audit(db, user.id, "DOWNLOAD_PDF", invoice.id, ip=ip, port=port, http_method="GET")
    db.commit()
    data = drive_service.download_and_decrypt(att.drive_file_id, att.encryption_key_enc)
    return data, att.drive_file_name or "anexo.pdf"


def delete_attachment(
    db: Session, invoice_id: str, attachment_id: str, user: User,
    ip: str | None = None, port: int | None = None,
) -> None:
    """Remove um anexo individual de uma nota (so o criador, status editavel)."""
    from app.models import InvoiceStatus
    from app.services.invoice_service.queries import _get_invoice

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
            detail="Anexos so podem ser removidos enquanto a nota e editavel",
        )
    att = next((a for a in invoice.attachments if a.id == attachment_id), None)
    if not att:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anexo nao encontrado")
    if len(invoice.attachments) <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A nota precisa ter pelo menos 1 anexo. Adicione outro antes de remover este.",
        )
    _delete_attachment_record(db, att)
    _add_audit(db, user.id, "DELETE_ATTACHMENT", invoice.id, ip=ip, port=port, http_method="DELETE")
    db.commit()
