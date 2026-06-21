"""CRUD basico de notas: create, list, get, update, delete.

Este sub-router define a rota /{invoice_id} bare (GET/PATCH/DELETE) que
deve ser INCLUIDA POR ULTIMO no facade pra nao shadowar rotas estaticas
como /directors e /lookup-cnpj/{cnpj}.
"""
import math
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.schemas.invoice import (
    InvoiceCreate,
    InvoiceResponse,
    InvoiceUpdate,
    PaginatedInvoices,
)
from app.security.dependencies import get_current_user, require_role
from app.services import invoice_service

from app.routers.invoices_helpers import (
    client_ip,
    client_port,
    invoice_response,
    prefetch_comment_counts,
    read_pdf_uploads,
    validation_to_422,
)


router = APIRouter()


@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    request: Request,
    invoice_number: str = Form(...),
    issue_date: date = Form(...),
    due_date: date = Form(...),
    description: str = Form(...),
    bank_details: Optional[str] = Form(default=None),
    amount: Decimal = Form(...),
    supplier_document: str = Form(...),
    supplier_name: Optional[str] = Form(default=None),
    supplier_legal_name: Optional[str] = Form(default=None),
    submit_now: bool = Form(default=True),
    director_id: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    parsed_files = await read_pdf_uploads(files)
    try:
        data = InvoiceCreate(
            invoice_number=invoice_number,
            issue_date=issue_date,
            due_date=due_date,
            description=description,
            bank_details=bank_details,
            amount=amount,
            supplier_document=supplier_document,
            supplier_name=supplier_name,
            supplier_legal_name=supplier_legal_name,
        )
    except ValidationError as exc:
        raise validation_to_422(exc) from exc
    invoice = invoice_service.create_invoice(
        db,
        data,
        current_user,
        files=parsed_files,
        ip=client_ip(request),
        port=client_port(request),
        submit_now=submit_now,
        director_id=director_id or None,
    )
    return invoice_response(invoice)


@router.get("/", response_model=PaginatedInvoices)
def list_invoices(
    status: str | None = None,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    due_from: str | None = None,
    due_to: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    created_by: str | None = None,
    supplier: str | None = None,
    department_id: str | None = None,
    fields: str | None = None,  # "light" usa loader leve (P2-5 auditoria)
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="Numero de pagina invalido.")
    if per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="Quantidade por pagina invalida.")
    light = (fields or "").lower() == "light"

    # Validacao de datas ISO — sem isso "from_date=abc" causa 500
    from datetime import date as _date
    for label, value in (("from_date", from_date), ("to_date", to_date), ("due_from", due_from), ("due_to", due_to)):
        if value:
            try:
                _date.fromisoformat(value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Data invalida em '{label}'. Use o formato dd/mm/aaaa.")

    items, total, total_amount = invoice_service.get_invoices_for_user(
        db,
        current_user,
        status_filter=status,
        page=page,
        per_page=per_page,
        search=search,
        from_date=from_date,
        to_date=to_date,
        due_from=due_from,
        due_to=due_to,
        min_amount=min_amount,
        max_amount=max_amount,
        created_by=created_by,
        supplier=supplier,
        department_id=department_id,
        light=light,
    )
    prefetch_comment_counts(db, [inv.id for inv in items])
    return PaginatedInvoices(
        items=[invoice_response(invoice) for invoice in items],
        total=total,
        page=page,
        per_page=per_page,
        pages=math.ceil(total / per_page) if total else 0,
        total_amount=total_amount,
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
def get_invoice(
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invoice = invoice_service.get_invoice_or_403(db, invoice_id, current_user)
    return invoice_response(invoice)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    invoice_service.delete_invoice(
        db, invoice_id, current_user,
        ip=client_ip(request), port=client_port(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: str,
    request: Request,
    invoice_number: Optional[str] = Form(default=None),
    issue_date: Optional[date] = Form(default=None),
    due_date: Optional[date] = Form(default=None),
    description: Optional[str] = Form(default=None),
    bank_details: Optional[str] = Form(default=None),
    amount: Optional[Decimal] = Form(default=None),
    supplier_document: Optional[str] = Form(default=None),
    supplier_name: Optional[str] = Form(default=None),
    supplier_legal_name: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    """PATCH adiciona NOVOS anexos (nao substitui). Pra remover use
    DELETE /{invoice_id}/attachments/{attachment_id}."""
    new_files = await read_pdf_uploads(files)
    try:
        data = InvoiceUpdate(
            **{
                key: value
                for key, value in {
                    "invoice_number": invoice_number,
                    "issue_date": issue_date,
                    "due_date": due_date,
                    "description": description,
                    "bank_details": bank_details,
                    "amount": amount,
                    "supplier_document": supplier_document,
                    "supplier_name": supplier_name,
                    "supplier_legal_name": supplier_legal_name,
                }.items()
                if value is not None
            }
        )
    except ValidationError as exc:
        raise validation_to_422(exc) from exc
    invoice = invoice_service.update_invoice(
        db,
        invoice_id,
        data,
        current_user,
        new_files=new_files,
        ip=client_ip(request),
        port=client_port(request),
    )
    return invoice_response(invoice)
