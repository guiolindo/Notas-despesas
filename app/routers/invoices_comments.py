"""Endpoints de comentarios: GET/POST /{id}/comments."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User
from app.security.dependencies import get_current_user
from app.services import invoice_service

from app.routers.invoices_helpers import CommentRequest, client_ip, client_port


router = APIRouter()


@router.get("/{invoice_id}/comments")
def list_comments(
    invoice_id: str,
    page: int = 1,
    per_page: int = 50,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista comentarios da nota em ordem cronologica, paginados.

    P2 da auditoria: antes retornava tudo num shot — nota com 200 comentarios
    pesava a query e o JS. Agora pagina (default 50 por pagina).

    Quem pode visualizar a nota pode ler os comentarios.
    """
    invoice = invoice_service.get_invoice_or_403(db, invoice_id, current_user)
    from app.models import InvoiceComment

    page = max(1, page)
    per_page = max(1, min(per_page, 200))

    base_query = (
        db.query(InvoiceComment)
        .filter(InvoiceComment.invoice_id == invoice.id)
    )
    total = base_query.count()
    comments = (
        base_query.order_by(InvoiceComment.created_at.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return {
        "items": [
            {
                "id": c.id,
                "body": c.body,
                "created_at": (
                    c.created_at.replace(tzinfo=None).isoformat()
                    if c.created_at and c.created_at.tzinfo is None
                    else (c.created_at.isoformat() if c.created_at else None)
                ),
                "user": {
                    "id": c.user.id,
                    "name": c.user.name,
                    "role": c.user.role.value,
                } if c.user else None,
            }
            for c in comments
        ],
        "page": page,
        "per_page": per_page,
        "total": total,
        "has_next": page * per_page < total,
    }


@router.post("/{invoice_id}/comments", status_code=status.HTTP_201_CREATED)
def add_comment(
    invoice_id: str,
    body: CommentRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Adiciona comentario na nota. Quem pode ver a nota pode comentar.
    Notifica por email os outros envolvidos no fluxo (criador, gestor,
    diretor atual) — exceto o proprio autor."""
    invoice = invoice_service.get_invoice_or_403(db, invoice_id, current_user)
    text = (body.body or "").strip()
    if len(text) < 1 or len(text) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="O comentario precisa ter entre 1 e 2000 caracteres.",
        )

    from app.models import InvoiceComment
    comment = InvoiceComment(
        id=str(uuid.uuid4()),
        invoice_id=invoice.id,
        user_id=current_user.id,
        body=text,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)

    # Audita
    invoice_service._add_audit(
        db, current_user.id, "ADD_COMMENT", invoice.id,
        ip=client_ip(request), port=client_port(request), http_method="POST",
    )
    db.commit()

    # Notifica envolvidos (best-effort)
    try:
        from app.services import email_service
        recipients = set()
        for user in (invoice.created_by, invoice.manager, invoice.director, invoice.finance):
            if user and user.id != current_user.id and user.email and not user.email.endswith("@desligado.local"):
                recipients.add((user.id, user.email, user.name or ""))
        for (_uid, email, name) in recipients:
            subject = f"Novo comentario na nota {invoice.invoice_number}"
            url = f"/invoices/{invoice.id}"
            preview = text if len(text) <= 200 else text[:200] + "..."
            html = (
                f"<p>Ola {name},</p>"
                f"<p><strong>{current_user.name}</strong> comentou na nota "
                f"<strong>{invoice.invoice_number}</strong>:</p>"
                f"<blockquote style='border-left:3px solid #ddd;padding-left:10px;color:#555'>{preview}</blockquote>"
                f"<p><a href='{url}'>Abrir a nota</a></p>"
            )
            email_service.send_email_async(email, subject, html, text=preview)
    except Exception:  # noqa: BLE001
        pass

    return {
        "id": comment.id,
        "body": comment.body,
        "created_at": comment.created_at.isoformat() if comment.created_at else None,
        "user": {
            "id": current_user.id,
            "name": current_user.name,
            "role": current_user.role.value,
        },
    }
