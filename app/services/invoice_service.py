import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ApprovalAction,
    ApprovalHistory,
    AuditLog,
    Invoice,
    InvoiceStatus,
    User,
    UserRole,
)
from app.services.drive_service import drive_service


FSM_TRANSITIONS = {
    "submit_to_manager": (InvoiceStatus.RASCUNHO, InvoiceStatus.AGUARDANDO_GESTOR),
    "submit_to_director": (InvoiceStatus.RASCUNHO, InvoiceStatus.AGUARDANDO_DIRETOR),
    "cancel": (None, InvoiceStatus.RASCUNHO),  # múltiplos status de origem — verificado manualmente
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


def _invoice_options() -> tuple:
    return (
        selectinload(Invoice.approval_history).selectinload(ApprovalHistory.user),
        selectinload(Invoice.created_by).selectinload(User.department_obj),
        selectinload(Invoice.manager),
        selectinload(Invoice.director),
        selectinload(Invoice.finance),
    )


def _get_invoice(db: Session, invoice_id: str) -> Invoice:
    invoice = (
        db.query(Invoice)
        .options(*_invoice_options())
        .filter(Invoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota nao encontrada")
    return invoice


def _assert_transition(invoice: Invoice, transition: str) -> InvoiceStatus:
    expected, target = FSM_TRANSITIONS[transition]
    if expected is not None and invoice.status != expected:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transicao invalida para status {invoice.status.value}",
        )
    return target


def _can_view(invoice: Invoice, user: User) -> bool:
    if user.role == UserRole.ADMIN:
        return True
    if user.role == UserRole.EMPLOYEE:
        return invoice.created_by_id == user.id
    if user.role == UserRole.MANAGER:
        return invoice.manager_id == user.id or (
            invoice.created_by is not None and invoice.created_by.manager_id == user.id
        )
    if user.role == UserRole.DIRECTOR:
        # Vê notas atribuídas a ele
        return invoice.director_id == user.id or invoice.status in {
            InvoiceStatus.APROVADO,
            InvoiceStatus.PAGO,
        }
    if user.role == UserRole.FINANCE:
        return invoice.status in {InvoiceStatus.APROVADO, InvoiceStatus.PAGO}
    return False


def _query_visible_invoices(db: Session, user: User):
    query = db.query(Invoice).options(*_invoice_options())
    if user.role == UserRole.ADMIN:
        return query
    if user.role == UserRole.EMPLOYEE:
        return query.filter(Invoice.created_by_id == user.id)
    if user.role == UserRole.MANAGER:
        return query.filter(Invoice.manager_id == user.id)
    if user.role == UserRole.DIRECTOR:
        # Vê notas destinadas a ele + notas aprovadas/pagas
        return query.filter(
            (Invoice.director_id == user.id)
            | Invoice.status.in_([InvoiceStatus.APROVADO, InvoiceStatus.PAGO])
        )
    if user.role == UserRole.FINANCE:
        return query.filter(Invoice.status.in_([InvoiceStatus.APROVADO, InvoiceStatus.PAGO]))
    return query.filter(False)


def _status_from_filter(status_filter: str | None) -> InvoiceStatus | None:
    if not status_filter:
        return None
    try:
        return InvoiceStatus(status_filter)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Status invalido",
        ) from exc


def _replace_attachment(
    invoice: Invoice,
    file_bytes: bytes | None,
    filename: str | None,
) -> None:
    if file_bytes is None:
        return
    if invoice.drive_file_id:
        drive_service.delete_file(invoice.drive_file_id)
    drive_file_id, encrypted_key = drive_service.upload_encrypted_file(
        file_bytes,
        filename or "nota.pdf",
    )
    invoice.drive_file_id = drive_file_id
    invoice.drive_file_name = filename
    invoice.encryption_key_enc = encrypted_key


def _get_director(db: Session, director_id: str) -> User:
    director = db.query(User).filter(
        User.id == director_id,
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
    ).first()
    if not director:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Diretor nao encontrado ou inativo",
        )
    return director


def _get_manager_for_user(db: Session, user: User) -> User:
    """Retorna o gestor do setor do funcionário."""
    if user.manager_id:
        manager = db.query(User).filter(User.id == user.manager_id).first()
        if manager:
            return manager
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Usuario sem gestor cadastrado. Contate o administrador.",
    )


def create_invoice(
    db: Session,
    data,
    user: User,
    file_bytes: bytes | None = None,
    filename: str | None = None,
    ip: str | None = None,
    port: int | None = None,
    submit_now: bool = False,
    director_id: str | None = None,
) -> Invoice:
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
    )
    _replace_attachment(invoice, file_bytes, filename)
    db.add(invoice)
    db.flush()
    _add_history(db, invoice.id, user.id, ApprovalAction.CREATED, ip=ip, port=port)
    _add_audit(db, user.id, "CREATE_INVOICE", invoice.id, ip=ip, port=port, http_method="POST")

    if submit_now:
        _do_submit(db, invoice, user, director_id, ip, port)

    db.commit()
    return _get_invoice(db, invoice.id)


def _do_submit(
    db: Session,
    invoice: Invoice,
    user: User,
    director_id: str | None,
    ip: str | None,
    port: int | None = None,
) -> None:
    """Lógica interna de envio — reutilizada em create e submit."""
    now = _now()
    invoice.submitted_at = now

    if user.submit_directly_to_director or (user.role == UserRole.MANAGER):
        # Envia direto ao diretor
        if not director_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Informe o diretor para envio direto",
            )
        director = _get_director(db, director_id)
        invoice.status = InvoiceStatus.AGUARDANDO_DIRETOR
        invoice.director_id = director.id
        # Se MANAGER cria e envia direto, ele mesmo é o gestor
        if user.role == UserRole.MANAGER:
            invoice.manager_id = user.id
            invoice.manager_reviewed_at = now
            _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
            _add_history(db, invoice.id, user.id, ApprovalAction.APPROVED_MANAGER,
                         comment="Enviado diretamente ao diretor pelo gestor", ip=ip, port=port)
        else:
            _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
        _add_audit(db, user.id, "SUBMIT_DIRECT_TO_DIRECTOR", invoice.id, ip=ip, port=port, http_method="POST")
    else:
        # Envia para o gestor do setor
        manager = _get_manager_for_user(db, user)
        invoice.status = InvoiceStatus.AGUARDANDO_GESTOR
        invoice.manager_id = manager.id
        _add_history(db, invoice.id, user.id, ApprovalAction.SUBMITTED, ip=ip, port=port)
        _add_audit(db, user.id, "SUBMIT_INVOICE", invoice.id, ip=ip, port=port, http_method="POST")


def submit_invoice(
    db: Session,
    invoice_id: str,
    user: User,
    director_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status != InvoiceStatus.RASCUNHO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nota no status {invoice.status.value} nao pode ser enviada",
        )
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
    # Verifica se nenhuma aprovação já aconteceu
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
    _add_history(db, invoice.id, user.id, ApprovalAction.CREATED,
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
            detail=f"Transicao invalida para status {invoice.status.value}",
        )

    invoice.manager_reviewed_at = _now()
    if action == "APPROVE":
        if not director_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Selecione o diretor para encaminhar a nota",
            )
        director = _get_director(db, director_id)
        invoice.director_id = director.id
        invoice.status = InvoiceStatus.AGUARDANDO_DIRETOR
        _add_history(db, invoice.id, manager.id, ApprovalAction.APPROVED_MANAGER, comment, ip, port)
        _add_audit(db, manager.id, "MANAGER_APPROVE", invoice.id, ip=ip, port=port, http_method="POST")
    else:
        invoice.status = InvoiceStatus.REPROVADO_GESTOR
        _add_history(db, invoice.id, manager.id, ApprovalAction.REJECTED_MANAGER, comment, ip, port)
        _add_audit(db, manager.id, "MANAGER_REJECT", invoice.id, ip=ip, port=port, http_method="POST")

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
            detail=f"Transicao invalida para status {invoice.status.value}",
        )

    invoice.director_reviewed_at = _now()
    if action == "APPROVE":
        invoice.status = InvoiceStatus.APROVADO
        _add_history(db, invoice.id, director.id, ApprovalAction.APPROVED_DIRECTOR, comment, ip, port)
        _add_audit(db, director.id, "DIRECTOR_APPROVE", invoice.id, ip=ip, port=port, http_method="POST")
    else:
        invoice.status = InvoiceStatus.REPROVADO_DIRETOR
        _add_history(db, invoice.id, director.id, ApprovalAction.REJECTED_DIRECTOR, comment, ip, port)
        _add_audit(db, director.id, "DIRECTOR_REJECT", invoice.id, ip=ip, port=port, http_method="POST")

    db.commit()
    return _get_invoice(db, invoice.id)


def get_invoices_for_user(
    db: Session,
    user: User,
    status_filter: str | None = None,
    page: int = 1,
    per_page: int = 20,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    min_amount: float | None = None,
    max_amount: float | None = None,
    created_by: str | None = None,
) -> tuple[list[Invoice], int]:
    query = _query_visible_invoices(db, user)
    invoice_status = _status_from_filter(status_filter)
    if invoice_status:
        query = query.filter(Invoice.status == invoice_status)

    # Busca livre em numero e descricao
    if search:
        term = f"%{search.strip()}%"
        query = query.filter(
            (Invoice.invoice_number.ilike(term)) | (Invoice.description.ilike(term))
        )

    # Faixa de datas (issue_date)
    if from_date:
        query = query.filter(Invoice.issue_date >= from_date)
    if to_date:
        query = query.filter(Invoice.issue_date <= to_date)

    # Faixa de valores
    if min_amount is not None:
        query = query.filter(Invoice.amount >= min_amount)
    if max_amount is not None:
        query = query.filter(Invoice.amount <= max_amount)

    # Filtro por responsavel (nome do criador)
    if created_by:
        creator_term = f"%{created_by.strip()}%"
        query = query.join(User, Invoice.created_by_id == User.id).filter(
            User.name.ilike(creator_term)
        )

    total = query.count()
    items = (
        query.order_by(Invoice.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total


def get_invoice_or_403(db: Session, invoice_id: str, user: User) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if not _can_view(invoice, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    return invoice


def get_attachment(db: Session, invoice_id: str, user: User, ip: str | None = None, port: int | None = None) -> bytes:
    invoice = get_invoice_or_403(db, invoice_id, user)
    if not invoice.drive_file_id or not invoice.encryption_key_enc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Anexo nao encontrado")
    _add_audit(db, user.id, "DOWNLOAD_PDF", invoice.id, ip=ip, port=port, http_method="GET")
    db.commit()
    return drive_service.download_and_decrypt(invoice.drive_file_id, invoice.encryption_key_enc)


def delete_invoice(db: Session, invoice_id: str, user: User, ip: str | None = None, port: int | None = None) -> None:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    if invoice.status != InvoiceStatus.RASCUNHO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas notas em rascunho podem ser excluidas",
        )
    if invoice.drive_file_id:
        drive_service.delete_file(invoice.drive_file_id)
    _add_audit(db, user.id, "DELETE_INVOICE", invoice.id, ip=ip, port=port, http_method="DELETE")
    db.delete(invoice)
    db.commit()


def update_invoice(
    db: Session,
    invoice_id: str,
    data,
    user: User,
    file_bytes: bytes | None = None,
    filename: str | None = None,
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
    if invoice.due_date < invoice.issue_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="due_date deve ser >= issue_date",
        )

    _replace_attachment(invoice, file_bytes, filename)
    _add_audit(db, user.id, "UPDATE_INVOICE", invoice.id, ip=ip, port=port, http_method="PATCH")
    db.commit()
    return _get_invoice(db, invoice.id)


def mark_paid(db: Session, invoice_id: str, finance_user: User, ip: str | None = None, port: int | None = None) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.status != InvoiceStatus.APROVADO:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Transicao invalida para status {invoice.status.value}",
        )
    invoice.status = InvoiceStatus.PAGO
    invoice.finance_id = finance_user.id
    invoice.paid_at = _now()
    _add_history(db, invoice.id, finance_user.id, ApprovalAction.MARKED_PAID, ip=ip, port=port)
    _add_audit(db, finance_user.id, "MARK_PAID", invoice.id, ip=ip, port=port, http_method="POST")
    db.commit()
    return _get_invoice(db, invoice.id)


def get_available_directors(db: Session, user: User) -> list[dict]:
    """Retorna lista de diretores com indicação de compatibilidade com o setor do usuário."""
    directors = db.query(User).filter(
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
    ).order_by(User.name).all()

    user_dept_id = user.department_id

    result = []
    for d in directors:
        dept_ids = {dept.id for dept in d.directed_departments}
        is_primary = user_dept_id is not None and user_dept_id in dept_ids
        dept_names = [dept.name for dept in d.directed_departments]
        result.append({
            "id": d.id,
            "name": d.name,
            "email": d.email,
            "is_primary": is_primary,
            "departments": dept_names,
        })

    # Ordenar: primário primeiro
    result.sort(key=lambda x: (not x["is_primary"], x["name"]))
    return result
