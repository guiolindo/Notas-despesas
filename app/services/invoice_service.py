import uuid
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy.orm import Session, selectinload

from app.models import (
    ApprovalAction,
    ApprovalHistory,
    AuditLog,
    Invoice,
    InvoiceAttachment,
    InvoiceStatus,
    User,
    UserRole,
)


MAX_ATTACHMENTS_PER_INVOICE = 5
MAX_TOTAL_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB

REJECTED_AUTO_DELETE_DAYS = 90  # notas reprovadas sao apagadas apos N dias
from app.services.drive_service import drive_service
from app.services import email_service


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
    """Quando diretor aprova, avisa TODOS do financeiro (em paralelo)."""
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


def _invoice_options() -> tuple:
    return (
        selectinload(Invoice.approval_history).selectinload(ApprovalHistory.user),
        selectinload(Invoice.created_by).selectinload(User.department_obj),
        selectinload(Invoice.manager),
        selectinload(Invoice.director),
        selectinload(Invoice.finance),
        selectinload(Invoice.attachments),
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
            detail="Esta acao nao pode ser feita na nota neste momento.",
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
        # Diretor ve: notas atribuidas a ele OU notas que ele proprio criou
        # (caso director-self-submit). Isolamento entre setores mantido.
        return invoice.director_id == user.id or invoice.created_by_id == user.id
    if user.role == UserRole.FINANCE:
        return invoice.status in {InvoiceStatus.APROVADO, InvoiceStatus.PAGO}
    if user.role == UserRole.CONTAS_A_PAGAR:
        # Contas a Pagar enxerga TODAS as notas — escaneia QR Code e
        # consulta para pagamento. Acesso read-only enforced nos endpoints.
        return True
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
        # Notas atribuidas a ele OR criadas por ele mesmo (self-submit)
        return query.filter(
            (Invoice.director_id == user.id) | (Invoice.created_by_id == user.id)
        )
    if user.role == UserRole.FINANCE:
        return query.filter(Invoice.status.in_([InvoiceStatus.APROVADO, InvoiceStatus.PAGO]))
    if user.role == UserRole.CONTAS_A_PAGAR:
        # Mesma visao do ADMIN para listagem; mas writes estao bloqueados
        # por require_role nos endpoints de mutacao.
        return query
    return query.filter(False)


def _status_from_filter(status_filter: str | None) -> InvoiceStatus | None:
    if not status_filter:
        return None
    try:
        return InvoiceStatus(status_filter)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filtro de status invalido.",
        ) from exc


def _sanitize_attachment_name(name: str | None) -> str:
    """Sanitiza nome do arquivo preservando legibilidade.
    Remove path traversal, caracteres especiais e limita tamanho.
    """
    if not name:
        return "anexo.pdf"
    from pathlib import Path
    import re
    base = Path(name).name  # remove path
    # Permite letras, numeros, espacos, ponto, hifen, underscore, parenteses
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
    individualmente. Falha de upload de QUALQUER um aborta a operacao
    (rollback do commit) — usuario nao fica com nota meio-vazia.
    """
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


def _delete_attachment(db: Session, attachment: InvoiceAttachment) -> None:
    """Apaga um anexo individual — arquivo no R2 + linha no banco.
    Best-effort no R2: se falhar, segue deletando o registro pra nao
    travar o usuario."""
    if attachment.drive_file_id:
        try:
            drive_service.delete_file(attachment.drive_file_id)
        except Exception:  # noqa: BLE001
            pass  # arquivo orfao no R2 — registrado mas nao bloqueia
    db.delete(attachment)


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
    # Diretor em ferias (unavailable_for_notes=True) nao aceita NOVA nota,
    # mas a validacao acontece aqui no momento do envio — UI ja oculta.
    if getattr(director, "unavailable_for_notes", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este diretor esta temporariamente indisponivel. Escolha outro.",
        )
    return director


def _get_manager_for_user(db: Session, user: User) -> User:
    """Retorna o gestor do setor do funcionario para receber uma nova nota.

    Exige que o gestor: (a) esteja ATIVO e (b) ainda tenha role MANAGER.
    Sem (b), funcionario com chefe promovido a DIRECTOR teria nota presa
    porque manager_review exige role MANAGER do aprovador.

    Quando o gestor esta indisponivel (`unavailable_for_notes=True` — ex.
    ferias), tenta delegar pro substitute_manager_id. Sem substituto valido,
    a submissao falha com mensagem clara. P1-9 da auditoria: antes, a flag
    de indisponibilidade era ignorada aqui e o funcionario seguia enviando
    pra fila do gestor em ferias.
    """
    if not user.manager_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel identificar seu gestor responsavel. Contate o administrador.",
        )

    manager = (
        db.query(User)
        .filter(
            User.id == user.manager_id,
            User.is_active.is_(True),
            User.role == UserRole.MANAGER,
        )
        .first()
    )
    if not manager:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nao foi possivel identificar seu gestor responsavel. Contate o administrador.",
        )

    if not getattr(manager, "unavailable_for_notes", False):
        return manager

    # Gestor em ferias: tenta substituto designado por ele.
    sub_id = getattr(manager, "substitute_manager_id", None)
    if sub_id:
        sub = (
            db.query(User)
            .filter(
                User.id == sub_id,
                User.is_active.is_(True),
                User.role == UserRole.MANAGER,
            )
            .first()
        )
        # Substituto tambem em ferias = sem rota. Nao cascateia infinitamente.
        if sub and not getattr(sub, "unavailable_for_notes", False):
            return sub

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=(
            "Seu gestor esta temporariamente indisponivel e nao designou um "
            "substituto ativo. Aguarde o retorno ou contate o administrador."
        ),
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
    supplier_doc = strip_non_digits(data.supplier_document)
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


def _do_submit(
    db: Session,
    invoice: Invoice,
    user: User,
    director_id: str | None,
    ip: str | None,
    port: int | None = None,
) -> None:
    """Lógica interna de envio — reutilizada em create e submit."""
    # Bloqueio defensivo: nota vencida nao pode ser submetida (vale tambem
    # para create_invoice com submit_now=True que chama esta funcao direto)
    from datetime import date as _date
    if invoice.due_date and invoice.due_date < _date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota com vencimento anterior a hoje nao pode ser enviada. Atualize o vencimento antes.",
        )
    now = _now()
    invoice.submitted_at = now

    if user.role == UserRole.DIRECTOR:
        # Diretor criando a propria nota — auto-aprovacao, vai direto ao Financeiro.
        # Pula etapas de gestor/diretor (ele mesmo e o diretor).
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
        # Delegacao automatica: se diretor estiver indisponivel e tiver
        # substituto designado, rota direto pra ele.
        director = _resolve_effective_director(db, director)
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
) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    # Aceita reenvio de notas reprovadas (apos edicao) — usuario nao precisa
    # criar nota nova a cada reprovacao.
    if invoice.status not in {
        InvoiceStatus.RASCUNHO,
        InvoiceStatus.REPROVADO_GESTOR,
        InvoiceStatus.REPROVADO_DIRETOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta nota nao pode ser enviada no momento.",
        )
    # Bloqueio: nota com vencimento ja passado nao pode ser enviada.
    # Aprovacao demoraria mais do que o titulo permite — sem sentido fiscal.
    from datetime import date as _date
    if invoice.due_date and invoice.due_date < _date.today():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nota com vencimento anterior a hoje nao pode ser enviada. Atualize o vencimento antes.",
        )
    # Anti-reenvio sem mudanca: se nota foi reprovada, exigir que a descricao
    # tenha sido editada antes do reenvio. Snapshot tirado na reprovacao
    # (manager_review/director_review REJECT).
    if invoice.status in {InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR}:
        snapshot = invoice.description_at_rejection
        if snapshot is not None and (invoice.description or "") == snapshot:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Edite a descricao antes de reenviar a nota.",
            )
    # Limpa rastros do roteamento anterior — novo envio pode ir pra outro
    # gestor/diretor (transferencia, mudanca de fluxo)
    invoice.manager_id = None
    invoice.director_id = None
    invoice.manager_reviewed_at = None
    invoice.director_reviewed_at = None
    invoice.description_at_rejection = None  # consumido — proxima reprovacao snapshot de novo
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
        # Delegacao automatica em ferias
        director = _resolve_effective_director(db, director)
        invoice.director_id = director.id
        invoice.status = InvoiceStatus.AGUARDANDO_DIRETOR
        _add_history(db, invoice.id, manager.id, ApprovalAction.APPROVED_MANAGER, comment, ip, port)
        _add_audit(db, manager.id, "MANAGER_APPROVE", invoice.id, ip=ip, port=port, http_method="POST")
        _notify_approver(db, director, invoice)
    else:
        invoice.status = InvoiceStatus.REPROVADO_GESTOR
        # Snapshot da descricao para forcar edicao antes de reenviar
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
    """Diretor atual repassa a nota pra outro diretor.

    Regras:
      - so o diretor atual da nota pode repassar
      - status precisa ser AGUARDANDO_DIRETOR (ja passou pelo gestor)
      - novo diretor deve ser ativo, com role DIRECTOR e nao indisponivel
      - comentario obrigatorio (minimo 10 chars) — fica no historico
      - novo diretor recebe email; ex-diretor recebe confirmacao
    """
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
    # Mantem status; reseta director_reviewed_at (ainda nao foi revisado pelo novo)
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
        # Confirmacao pro diretor que repassou
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


def _resolve_effective_director(db: Session, requested_director: User) -> User:
    """Se o diretor solicitado esta indisponivel e tem substituto ativo,
    retorna o substituto. Senao retorna o proprio. Usado em todos os
    pontos onde uma nota e roteada a um diretor."""
    if not getattr(requested_director, "unavailable_for_notes", False):
        return requested_director
    sub_id = getattr(requested_director, "substitute_director_id", None)
    if not sub_id:
        return requested_director  # sem substituto -> deixa cair na fila dele mesmo
    sub = db.query(User).filter(User.id == sub_id).first()
    if sub and sub.role == UserRole.DIRECTOR and sub.is_active and not getattr(sub, "unavailable_for_notes", False):
        return sub
    return requested_director


def _unaccent_or_lower(col):
    """Em Postgres usa unaccent() pra busca acento-insensivel; em SQLite
    cai em lower() simples. unaccent precisa da extension instalada
    (rodada em migration na primeira inicializacao)."""
    from app.database import engine
    from sqlalchemy import func as _func
    if engine.dialect.name == "postgresql":
        return _func.unaccent(_func.lower(col))
    return _func.lower(col)


def get_invoices_for_user(
    db: Session,
    user: User,
    status_filter: str | None = None,
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
) -> tuple[list[Invoice], int, float]:
    """Retorna (items_paginados, total_geral, soma_valor_total).

    A soma considera TODOS os itens que batem nos filtros, nao so da pagina
    atual — usada para exibir o totalizer no frontend.

    Parametros novos
    ----------------
    supplier: busca em supplier_name, supplier_legal_name e supplier_document
              (ja normaliza CPF/CNPJ se vier mascarado)
    department_id: filtra pelo setor do criador
    search: agora cobre tambem fornecedor; em Postgres usa unaccent
            pra busca acento-insensivel
    """
    from sqlalchemy import func, or_

    query = _query_visible_invoices(db, user)
    invoice_status = _status_from_filter(status_filter)
    if invoice_status:
        query = query.filter(Invoice.status == invoice_status)

    # Busca livre — agora cobre numero, descricao e fornecedor (acento-insensivel em PG)
    if search:
        term_raw = search.strip()
        like = f"%{term_raw.lower()}%"
        like_unaccent = f"%{term_raw.lower()}%"
        digits = "".join(c for c in term_raw if c.isdigit())
        clauses = [
            _unaccent_or_lower(Invoice.invoice_number).like(like_unaccent),
            _unaccent_or_lower(Invoice.description).like(like_unaccent),
            _unaccent_or_lower(Invoice.supplier_name).like(like_unaccent),
            _unaccent_or_lower(Invoice.supplier_legal_name).like(like_unaccent),
        ]
        if digits and len(digits) >= 3:
            # busca por CPF/CNPJ mesmo se usuario digitou com mascara
            clauses.append(Invoice.supplier_document.ilike(f"%{digits}%"))
        query = query.filter(or_(*clauses))

    # Filtro dedicado de fornecedor (campo separado nos avancados)
    if supplier:
        sup_raw = supplier.strip()
        sup_like = f"%{sup_raw.lower()}%"
        digits = "".join(c for c in sup_raw if c.isdigit())
        sup_clauses = [
            _unaccent_or_lower(Invoice.supplier_name).like(sup_like),
            _unaccent_or_lower(Invoice.supplier_legal_name).like(sup_like),
        ]
        if digits and len(digits) >= 3:
            sup_clauses.append(Invoice.supplier_document.ilike(f"%{digits}%"))
        query = query.filter(or_(*sup_clauses))

    # Filtro por setor (do criador da nota)
    if department_id:
        query = query.join(User, Invoice.created_by_id == User.id).filter(
            User.department_id == department_id
        )

    # Faixa de datas — emissao
    if from_date:
        query = query.filter(Invoice.issue_date >= from_date)
    if to_date:
        query = query.filter(Invoice.issue_date <= to_date)

    # Faixa de datas — vencimento
    if due_from:
        query = query.filter(Invoice.due_date >= due_from)
    if due_to:
        query = query.filter(Invoice.due_date <= due_to)

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
    # Soma sobre toda a query (nao so a pagina). Usa subquery_id para evitar
    # problema de SQLAlchemy com .count() apos with_entities().
    total_amount = float(
        db.query(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(Invoice.id.in_(query.with_entities(Invoice.id)))
        .scalar() or 0
    )
    items = (
        query.order_by(Invoice.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return items, total, total_amount


def get_invoice_or_403(db: Session, invoice_id: str, user: User) -> Invoice:
    invoice = _get_invoice(db, invoice_id)
    if not _can_view(invoice, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    return invoice


def get_attachment(
    db: Session,
    invoice_id: str,
    user: User,
    attachment_id: str | None = None,
    ip: str | None = None,
    port: int | None = None,
) -> tuple[bytes, str]:
    """Baixa um anexo especifico (se attachment_id passado) ou o primeiro
    anexo da nota (compatibilidade com codigo antigo).
    Retorna (bytes do PDF descriptografado, nome do arquivo)."""
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


def purge_old_rejected_invoices(db: Session) -> int:
    """Apaga notas reprovadas ha mais de REJECTED_AUTO_DELETE_DAYS dias.

    Roda no startup do app (idempotente — se ja apagado, no-op).
    Apaga arquivos no R2 + linha no banco (cascade limpa anexos+historico).
    Retorna quantidade apagada.

    Notas APROVADAS/LANCADAS NUNCA sao apagadas — obrigacao fiscal CTN 5 anos.
    """
    from datetime import datetime, timezone, timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=REJECTED_AUTO_DELETE_DAYS)
    # Tira tzinfo pra comparar com coluna DateTime naive
    cutoff_naive = cutoff.replace(tzinfo=None)

    old_rejected = (
        db.query(Invoice)
        .options(*_invoice_options())
        .filter(
            Invoice.status.in_([InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR]),
            # Usa o mais recente entre director_reviewed_at e manager_reviewed_at
            # — basta uma das datas ser velha o suficiente
            ((Invoice.director_reviewed_at != None) & (Invoice.director_reviewed_at < cutoff_naive))
            | ((Invoice.director_reviewed_at == None) & (Invoice.manager_reviewed_at < cutoff_naive)),
        )
        .all()
    )
    count = 0
    for inv in old_rejected:
        # Apaga anexos no R2 (best-effort)
        for att in list(inv.attachments):
            if att.drive_file_id:
                try:
                    drive_service.delete_file(att.drive_file_id)
                except Exception:  # noqa: BLE001
                    pass  # arquivo orfao — registrado e nao bloqueia
        # Audit ANTES de deletar (resource_id da referencia que vai sumir)
        _add_audit(
            db, None, "AUTO_DELETE_REJECTED", inv.id,
            detail=f"Removida automaticamente apos {REJECTED_AUTO_DELETE_DAYS} dias de reprovacao",
        )
        db.delete(inv)
        count += 1
    if count:
        db.commit()
    return count


def delete_invoice(db: Session, invoice_id: str, user: User, ip: str | None = None, port: int | None = None) -> None:
    invoice = _get_invoice(db, invoice_id)
    if invoice.created_by_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permissao insuficiente")
    # Status excluiveis: rascunho (nunca enviada) e reprovadas (saiu do fluxo).
    # Aprovadas/Pagas nao podem ser apagadas — obrigacao fiscal.
    if invoice.status not in {
        InvoiceStatus.RASCUNHO,
        InvoiceStatus.REPROVADO_GESTOR,
        InvoiceStatus.REPROVADO_DIRETOR,
    }:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="So e possivel excluir notas em rascunho ou reprovadas",
        )
    # Apaga TODOS os anexos no R2 (best-effort por arquivo)
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


def delete_attachment(
    db: Session, invoice_id: str, attachment_id: str, user: User,
    ip: str | None = None, port: int | None = None,
) -> None:
    """Remove um anexo individual de uma nota (so o criador, status editavel)."""
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
    _delete_attachment(db, att)
    _add_audit(db, user.id, "DELETE_ATTACHMENT", invoice.id, ip=ip, port=port, http_method="DELETE")
    db.commit()


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

    # Adiciona novos anexos (nao substitui existentes — pra trocar, usar
    # DELETE /attachments/{id} primeiro)
    if new_files:
        _add_attachments(db, invoice, new_files, uploaded_by_id=user.id)
    _add_audit(db, user.id, "UPDATE_INVOICE", invoice.id, ip=ip, port=port, http_method="PATCH")
    db.commit()
    return _get_invoice(db, invoice.id)


def mark_paid(db: Session, invoice_id: str, finance_user: User, ip: str | None = None, port: int | None = None) -> Invoice:
    # Defesa em profundidade: router ja exige role FINANCE, mas validamos
    # tambem aqui caso esta funcao seja chamada de outro contexto.
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


def get_available_directors(db: Session, user: User) -> list[dict]:
    """Retorna lista de diretores ativos e DISPONIVEIS para receber notas.
    Diretores em 'ferias' (unavailable_for_notes=True) sao omitidos —
    pessoa que esta enviando nota nao deve poder escolher quem esta de
    folga. Notas ja atribuidas seguem visiveis pro proprio diretor."""
    directors = db.query(User).filter(
        User.role == UserRole.DIRECTOR,
        User.is_active.is_(True),
        User.unavailable_for_notes.is_(False),
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
