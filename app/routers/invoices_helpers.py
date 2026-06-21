"""Helpers compartilhados entre os sub-routers de /api/invoices.

Split do `app/routers/invoices.py` (944 linhas) em jun/2026 (Fase 2 do
plan-refactor-master). Concentra:
  - Constantes (MAX_PDF_SIZE)
  - Helpers de IP/porta + datetime UTC
  - Computacao de alertas contextuais
  - Cache de comments_count via ContextVar (evita N+1)
  - Serializacao InvoiceResponse + ApprovalHistoryResponse
  - Validacao + leitura de PDF upload
  - Models locais (ManagerReviewAction, TransferDirectorRequest, CommentRequest)
"""
import contextvars as _ctxvars
import uuid

from fastapi import HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ValidationError
from typing import Optional

from app.models import ApprovalHistory, Invoice, InvoiceStatus
from app.schemas.invoice import (
    ApprovalHistoryResponse,
    InvoiceResponse,
    UserBrief,
)
from app.security.hashing import pseudonymize_ip


MAX_PDF_SIZE = 10 * 1024 * 1024


# ─── ValidationError → 422 ───────────────────────────────────────────────────


def validation_to_422(exc: ValidationError) -> HTTPException:
    """Converte ValidationError do Pydantic em 422 amigavel.

    Pentest jun/2026 (#SEC-9): rotas multipart instanciam manualmente
    InvoiceCreate/InvoiceUpdate, fora do path de body-binding do FastAPI.
    Sem este wrapper, ValidationError sobe como 500 — atacante distinguia
    erros de validacao reais (422) de inputs absurdos (500) e usava 500
    como fingerprint.
    """
    errs = exc.errors()
    first = errs[0] if errs else {"loc": (), "msg": "invalido", "type": "value_error"}
    field = ".".join(str(p) for p in first.get("loc", ()))
    msg = first.get("msg", "Dado invalido")
    detail = f"{field}: {msg}" if field else msg
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


# ─── Client info ─────────────────────────────────────────────────────────────


def client_ip(request: Request) -> str | None:
    raw = request.client.host if request.client else None
    return pseudonymize_ip(raw)


def client_port(request: Request) -> int | None:
    return request.client.port if request.client else None


def as_utc(dt):
    """Marca datetime naive como UTC (todos os _now() escrevem em UTC)."""
    if dt is None:
        return None
    from datetime import timezone as _tz
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)


# ─── Alertas contextuais no detalhe da nota ──────────────────────────────────


def compute_invoice_alerts(invoice) -> list[str]:
    """Avisos informativos no detalhe da nota.

    Para notas REPROVADAS: alertas focam na reprovacao (motivo + auto-delete).
    Para demais: alertas sobre o momento do ENVIO (emissao antiga, prazo curto).
    """
    from datetime import date as _date
    alerts: list[str] = []

    # Notas REPROVADAS: alerta focado, nao tem mais relevancia o vencimento
    if invoice.status in {InvoiceStatus.REPROVADO_GESTOR, InvoiceStatus.REPROVADO_DIRETOR}:
        rejection = next(
            (h for h in reversed(invoice.approval_history or [])
             if h.action.value.startswith("REJECTED")), None,
        )
        if rejection:
            reason = rejection.comment or "(motivo nao informado)"
            who = rejection.user.name if rejection.user else "aprovador"
            alerts.append(f"Reprovada por {who}: {reason}")

        # Aviso de auto-delete (apos 90 dias da reprovacao)
        ref_time = invoice.director_reviewed_at or invoice.manager_reviewed_at
        if ref_time:
            ref_date = ref_time.date() if hasattr(ref_time, "date") else ref_time
            days_since = (_date.today() - ref_date).days
            days_left = 90 - days_since
            if days_left <= 0:
                alerts.append("Esta nota sera removida automaticamente em breve (mais de 90 dias reprovada).")
            elif days_left <= 14:
                alerts.append(
                    f"Esta nota sera removida automaticamente em {days_left} dia(s). "
                    f"Edite a descricao e reenvie, ou aceite que ela sera arquivada."
                )
            else:
                alerts.append(
                    f"Reprovada ha {days_since} dia(s). Notas reprovadas sao removidas apos 90 dias."
                )
        return alerts

    is_submitted = bool(invoice.submitted_at)
    if is_submitted:
        ref = invoice.submitted_at.date() if hasattr(invoice.submitted_at, "date") else invoice.submitted_at
    else:
        ref = _date.today()

    # Emissao em ano/mes anterior a referencia — mensagem mais especifica pra ano
    if invoice.issue_date and (invoice.issue_date.year, invoice.issue_date.month) < (ref.year, ref.month):
        if invoice.issue_date.year < ref.year:
            year_label = (
                f"de {invoice.issue_date.year}" if (ref.year - invoice.issue_date.year) == 1
                else f"de {invoice.issue_date.year} (ha {ref.year - invoice.issue_date.year} anos)"
            )
            if is_submitted:
                alerts.append(f"Esta nota foi enviada com data de emissao {year_label}.")
            else:
                alerts.append(f"Data de emissao {year_label} — atenta-se ao prazo fiscal antes de enviar.")
        else:
            if is_submitted:
                alerts.append("Esta nota foi enviada com data de emissao do mes anterior.")
            else:
                alerts.append("Data de emissao e do mes anterior — atenta-se ao prazo fiscal antes de enviar.")

    # Vencimento dentro de 72h da data de envio
    if invoice.due_date:
        delta = (invoice.due_date - ref).days
        if 0 <= delta < 3:
            if delta == 0:
                when = "no proprio dia do vencimento"
            elif delta == 1:
                when = "a apenas 1 dia do vencimento"
            else:
                when = f"a apenas {delta} dias do vencimento"
            if is_submitted:
                alerts.append(f"Esta nota foi enviada {when}.")
            else:
                alerts.append(f"Se enviar agora, ficara {when}.")
    return alerts


# ─── Serializacao ────────────────────────────────────────────────────────────


def history_response(entry: ApprovalHistory) -> ApprovalHistoryResponse:
    return ApprovalHistoryResponse(
        id=entry.id,
        action=entry.action.value,
        comment=entry.comment,
        timestamp=as_utc(entry.timestamp),
        user=UserBrief.model_validate(entry.user),
    )


# Cache de comments_count por request. Listagem com 20 notas faria 20
# queries (N+1) — usuario reportou lag perceptivel de ~5s. Solucao: o
# endpoint de listagem chama prefetch_comment_counts ANTES do loop com
# uma unica query agrupada; cada invoice_response consulta este dict.
_COMMENT_COUNT_CACHE: "_ctxvars.ContextVar[dict[str, int] | None]" = _ctxvars.ContextVar(
    "comment_count_cache", default=None,
)


def prefetch_comment_counts(db, invoice_ids: list[str]) -> None:
    """Roda 1 SELECT invoice_id, COUNT(*) GROUP BY invoice_id pra todos os
    invoices da pagina. Resultado fica num dict consultado por
    count_comments dentro do mesmo request."""
    if not invoice_ids:
        _COMMENT_COUNT_CACHE.set({})
        return
    from sqlalchemy import func
    from app.models import InvoiceComment

    rows = (
        db.query(InvoiceComment.invoice_id, func.count(InvoiceComment.id))
        .filter(InvoiceComment.invoice_id.in_(invoice_ids))
        .group_by(InvoiceComment.invoice_id)
        .all()
    )
    cache = {inv_id: int(count) for inv_id, count in rows}
    for inv_id in invoice_ids:
        cache.setdefault(inv_id, 0)
    _COMMENT_COUNT_CACHE.set(cache)


def count_comments(invoice: Invoice) -> int:
    """Conta comentarios da nota. Usa cache do request quando disponivel
    (listagem pre-fetched), senao cai pra query individual (detail)."""
    cache = _COMMENT_COUNT_CACHE.get()
    if cache is not None and invoice.id in cache:
        return cache[invoice.id]
    from sqlalchemy import func
    from sqlalchemy.orm import object_session
    from app.models import InvoiceComment

    session = object_session(invoice)
    if session is None:
        return 0
    count = session.query(func.count(InvoiceComment.id)).filter(
        InvoiceComment.invoice_id == invoice.id
    ).scalar()
    return int(count or 0)


def invoice_response(invoice: Invoice) -> InvoiceResponse:
    from app.schemas.invoice import AttachmentBrief
    history = sorted(invoice.approval_history, key=lambda item: item.timestamp)
    dept = invoice.created_by.department_obj if invoice.created_by else None
    attachments = [
        AttachmentBrief(
            id=a.id,
            drive_file_name=a.drive_file_name,
            size_bytes=a.size_bytes or 0,
            uploaded_at=as_utc(a.uploaded_at),
        )
        for a in (invoice.attachments or [])
    ]
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        description=invoice.description,
        bank_details=invoice.bank_details,
        amount=invoice.amount,
        status=invoice.status.value,
        has_attachment=bool(invoice.attachments),
        attachments=attachments,
        supplier_document=invoice.supplier_document,
        supplier_document_type=invoice.supplier_document_type,
        supplier_name=invoice.supplier_name,
        supplier_legal_name=invoice.supplier_legal_name,
        created_by=UserBrief.model_validate(invoice.created_by),
        manager=UserBrief.model_validate(invoice.manager) if invoice.manager else None,
        director=UserBrief.model_validate(invoice.director) if invoice.director else None,
        created_at=as_utc(invoice.created_at),
        submitted_at=as_utc(invoice.submitted_at),
        manager_reviewed_at=as_utc(invoice.manager_reviewed_at),
        director_reviewed_at=as_utc(invoice.director_reviewed_at),
        paid_at=as_utc(invoice.paid_at),
        history=[history_response(entry) for entry in history],
        department_name=dept.name if dept else None,
        can_cancel=can_cancel(invoice),
        alerts=compute_invoice_alerts(invoice),
        comments_count=count_comments(invoice),
    )


def can_cancel(invoice: Invoice) -> bool:
    from app.models import ApprovalAction
    if invoice.status not in {InvoiceStatus.AGUARDANDO_GESTOR, InvoiceStatus.AGUARDANDO_DIRETOR}:
        return False
    approved = {ApprovalAction.APPROVED_MANAGER, ApprovalAction.APPROVED_DIRECTOR}
    return not any(h.action in approved for h in invoice.approval_history)


# ─── PDF upload validation ───────────────────────────────────────────────────


def check_pdf_safety(file_bytes: bytes) -> None:
    """Bloqueia PDFs que contem JavaScript embutido ou acoes automaticas
    (vetores comuns de execucao de codigo malicioso em leitores como
    Adobe Reader). Usa pypdf que ja esta nas dependencias.

    Tempo medio: 30-150ms para PDFs ate 10MB. Aceitavel para upload.
    Em caso de PDF corrompido/criptografado que nao parseia, libera
    (assume legitimo — bloquear forcaria usuarios honestos a refazer).
    """
    from io import BytesIO
    try:
        from pypdf import PdfReader
    except ImportError:
        return

    try:
        reader = PdfReader(BytesIO(file_bytes), strict=False)
    except Exception:
        return

    # 1. JavaScript embutido em nivel de documento (/Names -> /JavaScript)
    try:
        root = reader.trailer.get("/Root", {})
        names = root.get("/Names", {}) if root else {}
        if "/JavaScript" in (names or {}):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="PDF contem JavaScript embutido — nao permitido por seguranca.",
            )
    except HTTPException:
        raise
    except Exception:
        pass

    # 2. OpenAction
    try:
        if root and "/OpenAction" in root:
            action = root["/OpenAction"]
            try:
                action_obj = action.get_object() if hasattr(action, "get_object") else action
                if isinstance(action_obj, dict) and action_obj.get("/S") == "/JavaScript":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="PDF executa script automaticamente ao abrir — bloqueado.",
                    )
            except HTTPException:
                raise
            except Exception:
                pass

        # 3. AcroForm com JavaScript
        if root and "/AcroForm" in root:
            form = root["/AcroForm"]
            try:
                form_obj = form.get_object() if hasattr(form, "get_object") else form
                if isinstance(form_obj, dict) and "/JS" in str(form_obj.keys()):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="PDF contem formulario com JavaScript — bloqueado.",
                    )
            except HTTPException:
                raise
            except Exception:
                pass
    except HTTPException:
        raise
    except Exception:
        pass


async def read_pdf_upload(file: UploadFile | None) -> tuple[bytes | None, str | None]:
    if file is None:
        return None, None
    file_bytes = await file.read()
    if len(file_bytes) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo excede o limite de 10MB",
        )
    if not file_bytes.startswith(b"%PDF"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Arquivo enviado nao e um PDF valido",
        )
    check_pdf_safety(file_bytes)
    return file_bytes, f"{uuid.uuid4()}.pdf"


async def read_pdf_uploads(files: list[UploadFile] | None) -> list[tuple[bytes, str]]:
    """Le, valida e retorna lista de (bytes, filename_original) para multi-upload."""
    if not files:
        return []
    result = []
    for f in files:
        if f is None:
            continue
        if not f.filename:
            continue
        file_bytes = await f.read()
        if not file_bytes:
            continue
        if len(file_bytes) > MAX_PDF_SIZE:
            raise HTTPException(400, f"Arquivo '{f.filename}' excede o limite de 10MB por arquivo")
        if not file_bytes.startswith(b"%PDF"):
            raise HTTPException(400, f"'{f.filename}' nao parece ser um PDF valido")
        check_pdf_safety(file_bytes)
        result.append((file_bytes, f.filename))
    return result


# ─── Models locais usados em mais de um router ───────────────────────────────


class ManagerReviewAction(BaseModel):
    action: str
    comment: Optional[str] = None
    director_id: Optional[str] = None

    def validate_fields(self):
        if self.action not in ("APPROVE", "REJECT"):
            raise HTTPException(400, "action deve ser APPROVE ou REJECT")
        if self.action == "REJECT" and (not self.comment or len(self.comment.strip()) < 10):
            raise HTTPException(400, "Motivo obrigatorio ao reprovar (minimo 10 caracteres)")
        if self.action == "APPROVE" and not self.director_id:
            raise HTTPException(400, "Selecione o diretor para encaminhar a nota")


class TransferDirectorRequest(BaseModel):
    new_director_id: str
    comment: str


class CommentRequest(BaseModel):
    body: str
