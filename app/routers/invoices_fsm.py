"""Transicoes de estado da nota (FSM endpoints): submit, cancel, review,
director_review, transfer_director, mark_paid."""
from typing import Optional

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.schemas.invoice import InvoiceResponse, ReviewAction
from app.security.dependencies import require_role
from app.services import invoice_service

from app.routers.invoices_helpers import (
    ManagerReviewAction,
    TransferDirectorRequest,
    client_ip,
    client_port,
    invoice_response,
)


router = APIRouter()


@router.post("/{invoice_id}/submit", response_model=InvoiceResponse)
def submit_invoice(
    invoice_id: str,
    request: Request,
    director_id: Optional[str] = None,
    confirm_duplicate: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    invoice = invoice_service.submit_invoice(
        db, invoice_id, current_user,
        director_id=director_id,
        ip=client_ip(request),
        port=client_port(request),
        confirm_duplicate=confirm_duplicate,
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
def cancel_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value, UserRole.DIRECTOR.value)),
):
    invoice = invoice_service.cancel_invoice(
        db, invoice_id, current_user,
        ip=client_ip(request), port=client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/review", response_model=InvoiceResponse)
def manager_review(
    invoice_id: str,
    review: ManagerReviewAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.MANAGER.value)),
):
    review.validate_fields()
    invoice = invoice_service.manager_review(
        db,
        invoice_id,
        review.action,
        review.comment,
        current_user,
        director_id=review.director_id,
        ip=client_ip(request),
        port=client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/director-review", response_model=InvoiceResponse)
def director_review(
    invoice_id: str,
    review: ReviewAction,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DIRECTOR.value)),
):
    invoice = invoice_service.director_review(
        db,
        invoice_id,
        review.action,
        review.comment,
        current_user,
        ip=client_ip(request),
        port=client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/transfer-director", response_model=InvoiceResponse)
def transfer_director(
    invoice_id: str,
    body: TransferDirectorRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.DIRECTOR.value)),
):
    """Diretor atual repassa a nota pra outro diretor.

    Caso de uso: nota foi mal-encaminhada, conflito de interesse, ou o
    diretor reconhece que a aprovacao deveria ser de outra pessoa.
    """
    invoice = invoice_service.transfer_to_director(
        db,
        invoice_id,
        body.new_director_id,
        body.comment,
        current_user,
        ip=client_ip(request),
        port=client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceResponse)
def mark_paid(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FINANCE.value)),
):
    invoice = invoice_service.mark_paid(
        db, invoice_id, current_user,
        ip=client_ip(request), port=client_port(request),
    )
    return invoice_response(invoice)
