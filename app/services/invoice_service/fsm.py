"""State machine: submit, cancel, review (manager + director),
transfer, mark_paid, delete."""
from datetime import date as _date

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models import (
    ApprovalAction,
    Invoice,
    InvoiceStatus,
    User,
    UserRole,
)
from app.services import email_service
from app.services.drive_service import drive_service

from app.services.invoice_service._shared import (
    FSM_TRANSITIONS,
    _add_audit,
    _add_history,
    _now,
    _notify_approver,
    _notify_finance_team,
    _notify_rejection,
)
from app.services.invoice_service.directors import (
    _get_director,
    _get_manager_for_user,
    _resolve_effective_director,
)
from app.services.invoice_service.queries import _get_invoice


def _assert_transition(invoice: Invoice, transition: str) -> InvoiceStatus:
    expected, target = FSM_TRANSITIONS[transition]
    if expected is not None and invoice.status != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao nao pode ser feita na nota neste momento.",
        )
    return target


def _do_submit(
    db: Session,
    invoice: Invoice,
    user: User,
    director_id: str | None,
    ip: str | None,
    port: int | None = None,
) -> None:
    """Lógica interna de envio — reutilizada em create e submit."""
    if invoice.due_date and invoice.due_date < _date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota com vencimento anterior a hoje nao pode ser enviada. Atualize o vencimento antes.",
        )
    now = _now()
    invoice.submitted_at = now

    if user.role == UserRole.DIRECTOR:
        # Diretor criando a propria nota — auto-aprovacao, vai direto ao Financeiro.
        invoice.status = InvoiceStatus.APROVADO
        invoice.director_id = user.id
        invoice.director_reviewed_at = now
        _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
        _add_history(
            db, invoice.id, user.id, ApprovalAction.APPROVED_DIRECTOR,
            comment="Enviada diretamente ao Financeiro pelo proprio diretor",
            ip=ip, port=port,
        )
        _add_audit(db, user.id, "DIRECTOR_SELF_SUBMIT", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_finance_team(db, invoice)
    elif user.submit_directly_to_director or (user.role == UserRole.MANAGER):
        # Envia direto ao diretor
        if not director_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe o diretor para envio direto",
            )
        director = _get_director(db, director_id)
        director = _resolve_effective_director(db, director)
        invoice.status = InvoiceStatus.AGUARDANDO_DIRETOR
        invoice.director_id = director.id
        if user.role == UserRole.MANAGER:
            invoice.manager_id = user.id
            invoice.manager_reviewed_at = now
            _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
            _add_history(db, invoice.id, user.id, ApprovalAction.APPROVED_MANAGER,
                         comment="Enviado diretamente ao diretor pelo gestor", ip=ip, port=port)
        else:
            _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
        _add_audit(db, user.id, "SUBMIT_DIRECT_TO_DIRECTOR", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_approver(db, director, invoice)
    else:
        # Envia para o gestor do setor
        manager = _get_manager_for_user(db, user)
        invoice.status = InvoiceStatus.AGUARDANDO_GESTOR
        invoice.manager_id = manager.id
        _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
        _add_audit(db, user.id, "SUBMIT_INVOICE", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_approver(db, manager, invoice)


def submit_invoice(
    db: Session,
    invoice_id: str,
    user: User,
    director_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
    confirm_duplicate: bool = False,
) -> Invoice:
    from app.services.invoice_service.create import (
        _check_duplicate_invoice_number,
        _raise_duplicate_invoice_number,
    )

    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if not confirm_duplicate:
        existing = _check_duplicate_invoice_number(
            db,
            user_id=user.id,
            supplier_document=invoice.supplier_document,
            invoice_number=invoice.invoice_number,
            exclude_id=invoice.id,
        )
        if existing:
            _raise_duplicate_invoice_number(existing)
    if invoice.status not in {
        InvoiceStatus.RASCUNHO,
        InvoiceStatus.REPROVADO_GESTOR,
        InvoiceStatus.REPROVADO_DIRETOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta nota nao pode ser enviada no momento.",
        )
    if invoice.due_date and invoice.due_date < _date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota com vencimento anterior a hoje nao pode ser enviada. Atualize o vencimento antes.",
        )
    # Anti-reenvio sem mudanca: se nota foi reprovada, exigir que a descricao
    # tenha sido editada antes do reenvio. Snapshot tirado na reprovacao.
    if invoice.status in {InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR}:
        snapshot = invoice.description_at_rejection
        if snapshot is not None and (invoice.description or "") == snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Edite a descricao antes de reenviar a nota.",
            )
    # Limpa rastros do roteamento anterior
    invoice.manager_id = None
    invoice.director_id = None
    invoice.manager_reviewed_at = None
    invoice.director_reviewed_at = None
    invoice.description_at_rejection = None
    _do_submit(db, invoice, user, director_id, ip, port)
    db.commit()
    return _get_invoice(db, invoice.id)


def cancel_invoice(
    db: Session,
    invoice_id: str,
    user: User,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status not in {InvoiceStatus.AGUARDANDO_GESTOR, InvoiceStatus.AGUARDANDO_DIRETOR}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cancelamento disponivel apenas enquanto aguardando aprovacao",
        )
    approved_actions = {ApprovalAction.APPROVED_MANAGER, ApprovalAction.APPROVED_DIRECTOR}
    if any(h.action in approved_actions for h in invoice.approval_history):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota ja foi aprovada e nao pode ser cancelada",
        )
    invoice.status = InvoiceStatus.RASCUNHO
    invoice.director_id = None
    invoice.manager_id = None
    invoice.submitted_at = None
    _add_history(db, invoice.id, user.id, ApprovalAction.CANCELLED,
                 comment="Envio cancelado pelo criador", ip=ip, port=port)
    _add_audit(db, user.id, "CANCEL_INVOICE", invoice.id, ip=ip, port=port, http_method="POST")
    db.commit()
    return _get_invoice(db, invoice.id)


def manager_review(
    db: Session,
    invoice_id: str,
    action: str,
    comment: str | None,
    manager: User,
    director_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.manager_id != manager.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status != InvoiceStatus.AGUARDANDO_GESTOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao nao pode ser feita na nota neste momento.",
        )

    invoice.manager_reviewed_at = _now()
    if action == "APPROVE":
        if not director_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selecione o diretor para encaminhar a nota",
            )
        director = _get_director(db, director_id)
        director = _resolve_effective_director(db, director)
        invoice.director_id = director.id
        invoice.status = InvoiceStatus.AGUARDANDO_DIRETOR
        _add_history(db, invoice.id, manager.id, ApprovalAction.APPROVED_MANAGER, comment, ip, port)
        _add_audit(db, manager.id, "MANAGER_APPROVE", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_approver(db, director, invoice)
    else:
        invoice.status = InvoiceStatus.REPROVADO_GESTOR
        invoice.description_at_rejection = invoice.description or ""
        _add_history(db, invoice.id, manager.id, ApprovalAction.REJECTED_MANAGER, comment, ip, port)
        _add_audit(db, manager.id, "MANAGER_REJECT", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_rejection(db, invoice, manager, comment)

    db.commit()
    return _get_invoice(db, invoice.id)


def director_review(
    db: Session,
    invoice_id: str,
    action: str,
    comment: str | None,
    director: User,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.director_id != director.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status != InvoiceStatus.AGUARDANDO_DIRETOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao nao pode ser feita na nota neste momento.",
        )

    invoice.director_reviewed_at = _now()
    if action == "APPROVE":
        invoice.status = InvoiceStatus.APROVADO
        _add_history(db, invoice.id, director.id, ApprovalAction.APPROVED_DIRECTOR, comment, ip, port)
        _add_audit(db, director.id, "DIRECTOR_APPROVE", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_finance_team(db, invoice)
    else:
        invoice.status = InvoiceStatus.REPROVADO_DIRETOR
        invoice.description_at_rejection = invoice.description or ""
        _add_history(db, invoice.id, director.id, ApprovalAction.REJECTED_DIRECTOR, comment, ip, port)
        _add_audit(db, director.id, "DIRECTOR_REJECT", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_rejection(db, invoice, director, comment)

    db.commit()
    return _get_invoice(db, invoice.id)


def transfer_to_director(
    db: Session,
    invoice_id: str,
    new_director_id: str,
    comment: str | None,
    current_director: User,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    """Diretor atual repassa a nota pra outro diretor."""
    invoice = _get_invoice(db, invoice_id)
    if invoice.director_id != current_director.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Apenas o diretor atualmente responsavel pode repassar esta nota.",
        )
    if invoice.status != InvoiceStatus.AGUARDANDO_DIRETOR:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="So e possivel repassar enquanto a nota aguarda sua aprovacao.",
        )
    if not comment or len(comment.strip()) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Informe o motivo do repasse (minimo 10 caracteres).",
        )
    if new_director_id == current_director.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Voce nao pode repassar a nota para voce mesmo.",
        )

    new_director = db.query(User).filter(User.id == new_director_id).first()
    if not new_director or new_director.role != UserRole.DIRECTOR or not new_director.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diretor de destino invalido ou inativo.",
        )
    if getattr(new_director, "unavailable_for_notes", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diretor de destino esta temporariamente indisponivel. Escolha outro.",
        )

    previous_director = current_director
    invoice.director_id = new_director.id
    invoice.director_reviewed_at = None

    full_comment = (
        f"Repassada de {previous_director.name} para {new_director.name}. "
        f"Motivo: {comment.strip()}"
    )
    _add_history(
        db, invoice.id, previous_director.id,
        ApprovalAction.TRANSFERRED_DIRECTOR, full_comment, ip, port,
    )
    _add_audit(
        db, previous_director.id, "TRANSFER_DIRECTOR", invoice.id,
        ip=ip, port=port, http_method="POST",
    )

    # Notifica o novo diretor (mesmo template de submissao)
    try:
        public_url = f"/director/invoices/{invoice.id}"
        subject, html, text = email_service.template_new_invoice_for_approver(
            approver_name=new_director.name,
            creator_name=invoice.created_by.name if invoice.created_by else "?",
            invoice_number=invoice.invoice_number,
            amount=f"R$ {invoice.amount:.2f}".replace(".", ","),
            public_url=public_url,
        )
        if new_director.email:
            email_service.send_email_async(new_director.email, subject, html, text)
        if previous_director.email:
            email_service.send_email_async(
                previous_director.email,
                subject=f"Repasse confirmado — nota {invoice.invoice_number}",
                html=(
                    f"<p>Ola {previous_director.name},</p>"
                    f"<p>A nota <strong>{invoice.invoice_number}</strong> foi "
                    f"repassada para <strong>{new_director.name}</strong> "
                    f"conforme sua solicitacao.</p>"
                    f"<p>Motivo registrado: {comment.strip()}</p>"
                ),
            )
    except Exception:  # noqa: BLE001
        pass

    db.commit()
    return _get_invoice(db, invoice.id)


def mark_paid(db: Session, invoice_id: str, finance_user: User, ip: str | None = None, port: int | None = None) -> Invoice:
    if finance_user.role not in {UserRole.FINANCE, UserRole.ADMIN}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    invoice = _get_invoice(db, invoice_id)
    if invoice.status != InvoiceStatus.APROVADO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta acao nao pode ser feita na nota neste momento.",
        )
    invoice.status = InvoiceStatus.PAGO
    invoice.finance_id = finance_user.id
    invoice.paid_at = _now()
    _add_history(db, invoice.id, finance_user.id, ApprovalAction.MARKED_PAID, ip=ip, port=port)
    _add_audit(db, finance_user.id, "MARK_PAID", invoice.id, ip=ip, port=port, http_method="POST")
    db.commit()
    return _get_invoice(db, invoice.id)


def delete_invoice(db: Session, invoice_id: str, user: User, ip: str | None = None, port: int | None = None) -> None:
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
            detail="So e possivel excluir notas em rascunho ou reprovadas",
        )
    storage_warnings = []
    for att in list(invoice.attachments):
        if att.drive_file_id:
            try:
                drive_service.delete_file(att.drive_file_id)
            except Exception as exc:  # noqa: BLE001
                storage_warnings.append(f"{att.drive_file_id}: {exc}")
    _add_audit(
        db, user.id, "DELETE_INVOICE", invoice.id,
        ip=ip, port=port, http_method="DELETE",
        detail="; ".join(storage_warnings) if storage_warnings else None,
    )
    db.delete(invoice)  # cascade=delete-orphan apaga attachments do banco
    db.commit()
