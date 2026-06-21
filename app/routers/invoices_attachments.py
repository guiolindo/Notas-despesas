"""Endpoints de anexos: GET /{id}/attachment (merged), GET/DELETE de
/{id}/attachments/{att_id}."""
import io

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.security.dependencies import get_current_user, require_role
from app.services import invoice_service

from app.routers.invoices_helpers import client_ip, client_port


router = APIRouter()


@router.get("/{invoice_id}/attachment")
def get_attachment_merged(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna TODOS os anexos da nota mesclados em um PDF unico, na ordem
    de upload. Usado no iframe de visualizacao e no botao 'Abrir em nova aba'.

    Cada anexo e descriptografado individualmente e suas paginas sao
    concatenadas. Falha em um anexo (corrompido, R2 fora) e ignorada —
    visualizacao segue com os outros."""
    invoice = invoice_service.get_invoice_or_403(db, invoice_id, current_user)
    if not invoice.attachments:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nenhum anexo encontrado")

    from pypdf import PdfReader, PdfWriter
    from app.services.drive_service import drive_service as _ds
    writer = PdfWriter()
    for att in invoice.attachments:
        if not att.drive_file_id or not att.encryption_key_enc:
            continue
        try:
            data = _ds.download_and_decrypt(att.drive_file_id, att.encryption_key_enc)
            for page in PdfReader(io.BytesIO(data)).pages:
                writer.add_page(page)
        except Exception:  # noqa: BLE001
            continue

    if len(writer.pages) == 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Nao foi possivel abrir os anexos desta nota.")

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    # Audit log de visualizacao
    invoice_service._add_audit(
        db, current_user.id, "VIEW_PDF_MERGED", invoice.id,
        ip=client_ip(request), port=client_port(request), http_method="GET",
    )
    db.commit()

    safe_number = invoice.invoice_number.replace("/", "-").replace("\\", "-")
    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="nota_{safe_number}.pdf"'},
    )


@router.get("/{invoice_id}/attachments/{attachment_id}")
def get_attachment_by_id(
    invoice_id: str,
    attachment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Baixa um anexo especifico da nota (suporta multi-PDF)."""
    pdf_bytes, original_name = invoice_service.get_attachment(
        db, invoice_id, current_user, attachment_id=attachment_id,
        ip=client_ip(request), port=client_port(request),
    )
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{original_name}"'},
    )


@router.delete("/{invoice_id}/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_attachment(
    invoice_id: str,
    attachment_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    """Remove um anexo individual da nota (so criador, status editavel)."""
    invoice_service.delete_attachment(
        db, invoice_id, attachment_id, current_user,
        ip=client_ip(request), port=client_port(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
