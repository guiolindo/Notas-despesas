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
from app.services.document_service import (
    format_cnpj,
    format_cpf,
    mask_document,
    mask_name,
)
from app.services.drive_service import drive_service
from app.services.pdf_service import generate_print_pdf, invoice_hash


def _cached_or_generate_pdf(invoice: Invoice, base_url: str) -> bytes:
    """PERF-02 (auditoria set/2026): antes gerava PDF do zero a cada
    print/mark-paid — baixar N anexos do R2, descriptografar cada um,
    concatenar. Segundos por chamada, worker bloqueado.

    Agora: se a nota ja tem print_drive_file_id armazenado (isto e,
    ja foi gerada uma vez apos APROVADO), tenta baixar do R2. Se o
    download falhar (chave errada, arquivo removido), regenera. Se
    ainda nao existe, gera + guarda para as proximas reimpressoes.

    Chave de encriptacao reusa encryption_key_enc da nota — se ela
    existe (anexo do usuario original criptografado). Se nao (nota sem
    anexo criptografado — edge case DEV), guarda sem encriptar.
    """
    cache_id = getattr(invoice, "print_drive_file_id", None)
    if cache_id and invoice.encryption_key_enc:
        try:
            return drive_service.download_and_decrypt(
                cache_id, invoice.encryption_key_enc,
            )
        except Exception:
            # Cache invalido — regenera e sobrescreve.
            pass
    pdf_bytes = generate_print_pdf(invoice, base_url)
    return pdf_bytes


def _persist_pdf_cache(db, invoice: Invoice, pdf_bytes: bytes) -> None:
    """Guarda o PDF no R2 e associa a nota."""
    if not invoice.encryption_key_enc:
        # Sem chave original — nao persiste (edge DEV).
        return
    try:
        from app.services.drive_service import (
            decrypt_key_with_master, encrypt_data,
        )
        # Descriptografa a chave da nota, encripta o PDF com ela, sobe.
        file_key = decrypt_key_with_master(invoice.encryption_key_enc)
        encrypted = encrypt_data(pdf_bytes, file_key)
        client = drive_service._client()
        if client is None:
            return  # fallback local — nao persiste
        import uuid as _uuid
        from app.config import settings
        obj_key = f"print-{_uuid.uuid4()}.enc"
        client.put_object(
            Bucket=settings.R2_BUCKET_NAME,
            Key=obj_key,
            Body=encrypted,
            ContentType="application/octet-stream",
            Metadata={"kind": "print", "invoice_id": invoice.id[:36]},
        )
        invoice.print_drive_file_id = obj_key
        db.commit()
    except Exception as exc:  # noqa: BLE001
        import logging as _lg
        _lg.getLogger(__name__).warning(
            "[print] falha ao persistir cache do PDF %s: %s", invoice.id, exc,
        )


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


def _pdf_streaming_response(invoice: Invoice, pdf_bytes: bytes) -> StreamingResponse:
    safe_number = invoice.invoice_number.replace("/", "-").replace("\\", "-")
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="nota_{safe_number}_comprovante.pdf"'},
    )


def _load_printable_invoice(db: Session, invoice_id: str) -> Invoice:
    """Carrega a nota se for imprimivel (APROVADO ou PAGO).

    404 quando a nota nao existe; mesmo 404 (e nao 400) quando o status nao
    permite impressao: evita que cliente externo distinga 'existe mas nao
    aprovada' de 'nao existe' — relevante porque invoice_id e UUID adivinhavel
    quando logs vazam.
    """
    invoice = _invoice_with_relations(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota nao encontrada")
    if invoice.status not in {InvoiceStatus.APROVADO, InvoiceStatus.PAGO}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Apenas notas aprovadas ou pagas podem ter comprovante gerado.",
        )
    return invoice


# =============================================================================
# IMPRESSAO / COMPROVANTE
#
# A separacao GET preview vs POST mark-paid corrige o achado P0 da auditoria:
# antes, GET /print disparava lancamento financeiro (state mutation em rota
# de leitura), o que viola semantica HTTP e permite que reload/preview-link/
# crawler dispare PAGO acidental. Agora:
#
#   GET  /api/invoices/{id}/print         -> preview (sem efeito colateral).
#                                            Para reimpressao de nota ja PAGA.
#   POST /api/invoices/{id}/mark-paid     -> acao explicita de lancamento.
#                                            Marca PAGO + retorna PDF.
#                                            Idempotente: se ja PAGO, devolve
#                                            o comprovante mas nao re-registra.
# =============================================================================


@router.get("/api/invoices/{invoice_id}/print")
def print_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(
        UserRole.FINANCE.value, UserRole.ADMIN.value, UserRole.CONTAS_A_PAGAR.value
    )),
):
    """Preview / reimpressao do comprovante.

    Sem efeito colateral. Apenas gera o PDF e devolve. Audit nao registra
    reimpressoes pra evitar poluicao (mesma politica da versao antiga). Quem
    quer DISPARAR o lancamento financeiro deve chamar POST /mark-paid.

    CONTAS_A_PAGAR (read-only) so pode reimprimir notas ja lancadas.
    """
    invoice = _load_printable_invoice(db, invoice_id)
    if (
        current_user.role.value == "CONTAS_A_PAGAR"
        and invoice.status != InvoiceStatus.PAGO
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contas a Pagar so pode reimprimir notas ja lancadas pelo Financeiro.",
        )
    # PERF-02: usa cache quando a nota ja foi paga uma vez.
    pdf_bytes = _cached_or_generate_pdf(invoice, str(request.base_url))
    return _pdf_streaming_response(invoice, pdf_bytes)


@router.post("/api/invoices/{invoice_id}/mark-paid")
def mark_paid(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(
        UserRole.FINANCE.value, UserRole.ADMIN.value
    )),
):
    """Lanca a nota (status APROVADO -> PAGO) e devolve o comprovante.

    Acao explicita: POST com confirmacao do usuario na UI. Idempotente: se a
    nota ja esta PAGO, gera o PDF e devolve sem alterar estado nem registrar
    de novo. ADMIN e FINANCE podem chamar; CONTAS_A_PAGAR nao (read-only).
    """
    invoice = _load_printable_invoice(db, invoice_id)
    pdf_bytes = _cached_or_generate_pdf(invoice, str(request.base_url))
    now = datetime.now(timezone.utc)
    _ip = pseudonymize_ip(request.client.host if request.client else None)
    _port = request.client.port if request.client else None

    if invoice.status == InvoiceStatus.APROVADO:
        # Transicao: APROVADO -> PAGO. Registra historico e auditoria so
        # nesta transicao real. Tambem grava printed_at/by porque na pratica
        # o usuario gera o comprovante no mesmo clique.
        invoice.status = InvoiceStatus.PAGO
        invoice.paid_at = now
        invoice.finance_id = current_user.id
        invoice.printed_at = now
        invoice.printed_by_id = current_user.id
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
            ApprovalHistory(
                id=str(uuid.uuid4()),
                invoice_id=invoice.id,
                user_id=current_user.id,
                action=ApprovalAction.MARKED_PAID,
                comment="Lancada via acao explicita (POST mark-paid)",
                timestamp=now,
                ip_address=_ip,
                source_port=_port,
            )
        )
        db.add(
            AuditLog(
                id=str(uuid.uuid4()),
                user_id=current_user.id,
                action="MARK_PAID",
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
        # PERF-02: persiste o PDF pra reimpressoes futuras ficarem
        # rapidas. So faz na transicao real APROVADO->PAGO — se ja
        # esta PAGO e chegou aqui, o cache_or_generate ja tratou.
        _persist_pdf_cache(db, invoice, pdf_bytes)
    # Se ja PAGO, idempotente: devolve o PDF sem mexer no estado.
    return _pdf_streaming_response(invoice, pdf_bytes)


def _mask_email(email: str | None) -> str | None:
    """Mascara email mantendo dica de identidade.
    'maria.silva@economart.com.br' -> 'maria.s****@economart.com.br'
    Quem e da empresa reconhece, quem nao e nao consegue extrair o email completo.
    """
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked_local = local[0] + "****"
    else:
        keep = max(2, len(local) // 3)
        masked_local = local[:keep] + "****"
    return f"{masked_local}@{domain}"


def _format_amount_brl(amount) -> str:
    try:
        v = float(amount)
        return f"R$ {v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:  # noqa: BLE001
        return f"R$ {amount}"


def _br_datetime(dt) -> str | None:
    if not dt:
        return None
    from datetime import timezone as _tz, timedelta as _td
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_tz.utc)
    return dt.astimezone(_tz(_td(hours=-3))).strftime("%d/%m/%Y %H:%M")


def _user_has_invoice_access(user: User, invoice: Invoice) -> bool:
    """ARQ-04 (auditoria set/2026): consolidado na fonte canonica
    invoice_service.queries._can_view. Antes tinha 3 versoes distintas
    (aqui, queries._can_view, e a logica implicita no _query_visible_
    invoices) com regras divergentes — este era o unico que concedia
    a CONTAS_A_PAGAR e continha comentario obsoleto sobre 'Fase 3'.
    """
    if not user or not invoice:
        return False
    from app.services.invoice_service import _can_view
    return _can_view(invoice, user)


@router.get("/verify/{invoice_id}", response_class=HTMLResponse)
def verify_invoice(invoice_id: str, request: Request, db: Session = Depends(get_db)):
    """Pagina publica de verificacao com mascara LGPD.

    Renderiza SEMPRE com dados mascarados; o JS detecta sessao
    autenticada (localStorage.access_token) e chama /verify-full pra revelar.
    """
    invoice = _invoice_with_relations(db, invoice_id)
    context = {
        "request": request,
        "invoice": invoice,
        "auth_hash": None,
        "director_reviewed_at_br": None,
        "amount_formatted": "-",
        # Dados mascarados (LGPD) — visiveis sem login
        "manager_name_masked": None,
        "director_name_masked": None,
        "supplier_name_masked": None,
        "supplier_doc_masked": None,
        "supplier_doc_type": None,
        "status_label": None,
        "department_name": None,
    }
    if invoice:
        context["auth_hash"] = invoice_hash(invoice)
        context["director_reviewed_at_br"] = _br_datetime(invoice.director_reviewed_at)
        context["amount_formatted"] = _format_amount_brl(invoice.amount)
        context["status_label"] = "LANCADO" if invoice.status.value == "PAGO" else invoice.status.value
        _dept = invoice.created_by.department_obj if invoice.created_by else None
        context["department_name"] = _dept.name if _dept else None
        context["manager_name_masked"] = mask_name(invoice.manager.name if invoice.manager else None)
        context["director_name_masked"] = mask_name(invoice.director.name if invoice.director else None)
        context["supplier_name_masked"] = mask_name(
            invoice.supplier_legal_name or invoice.supplier_name
        ) if (invoice.supplier_legal_name or invoice.supplier_name) else None
        context["supplier_doc_masked"] = mask_document(
            invoice.supplier_document, invoice.supplier_document_type
        ) if invoice.supplier_document else None
        context["supplier_doc_type"] = invoice.supplier_document_type
    return templates.TemplateResponse(request, "verify.html", context)


@router.get("/api/invoices/{invoice_id}/verify-full")
def verify_full(
    invoice_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retorna dados completos da nota para usuarios autorizados.

    Acesso: ADMIN, FINANCE, CONTAS_A_PAGAR, ou criador/gestor/diretor da nota.
    """
    # Resposta indistinguivel pra usuario sem acesso (P1 da auditoria):
    # antes, 404 quando nao existia e 403 quando existia sem permissao —
    # vazava existencia de recurso (oraculo por probing de UUID). Agora, a
    # mesma 404 cobre ambos. Quem nao deveria ver, nao consegue inferir.
    invoice = _invoice_with_relations(db, invoice_id)
    if not invoice or not _user_has_invoice_access(current_user, invoice):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Nota nao encontrada")
    # Documento formatado
    supplier_doc_fmt = None
    if invoice.supplier_document:
        if invoice.supplier_document_type == "CPF":
            supplier_doc_fmt = format_cpf(invoice.supplier_document)
        elif invoice.supplier_document_type == "CNPJ":
            supplier_doc_fmt = format_cnpj(invoice.supplier_document)
        else:
            supplier_doc_fmt = invoice.supplier_document
    _dept = invoice.created_by.department_obj if invoice.created_by else None
    return {
        "invoice_number": invoice.invoice_number,
        "status": "LANCADO" if invoice.status.value == "PAGO" else invoice.status.value,
        "amount_formatted": _format_amount_brl(invoice.amount),
        "department_name": _dept.name if _dept else None,
        "issue_date": invoice.issue_date.strftime("%d/%m/%Y") if invoice.issue_date else None,
        "due_date": invoice.due_date.strftime("%d/%m/%Y") if invoice.due_date else None,
        "director_reviewed_at_br": _br_datetime(invoice.director_reviewed_at),
        # SEC-12 (auditoria set/2026): mascara email pra evitar que
        # CONTAS_A_PAGAR extraia lista completa de gestores/diretores da
        # organizacao (insumo primario pra phishing direcionado).
        "manager_name": invoice.manager.name if invoice.manager else None,
        "manager_email": _mask_email(invoice.manager.email) if invoice.manager else None,
        "director_name": invoice.director.name if invoice.director else None,
        "director_email": _mask_email(invoice.director.email) if invoice.director else None,
        "created_by_name": invoice.created_by.name if invoice.created_by else None,
        "supplier_document": supplier_doc_fmt,
        "supplier_document_type": invoice.supplier_document_type,
        "supplier_name": invoice.supplier_name,
        "supplier_legal_name": invoice.supplier_legal_name,
        "description": invoice.description,
        "auth_hash": invoice_hash(invoice),
    }
