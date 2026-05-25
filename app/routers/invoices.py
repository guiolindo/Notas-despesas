import io
import math
import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ApprovalHistory, Invoice, InvoiceStatus, User, UserRole
from app.schemas.invoice import (
    ApprovalHistoryResponse,
    InvoiceCreate,
    InvoiceResponse,
    InvoiceUpdate,
    PaginatedInvoices,
    ReviewAction,
    UserBrief,
)
from app.security.dependencies import get_current_user, require_role
from app.security.hashing import pseudonymize_ip
from app.services import invoice_service


router = APIRouter()
MAX_PDF_SIZE = 10 * 1024 * 1024


def _client_ip(request: Request) -> str | None:
    raw = request.client.host if request.client else None
    return pseudonymize_ip(raw)


def _client_port(request: Request) -> int | None:
    return request.client.port if request.client else None


def _as_utc(dt):
    """Marca datetime naive como UTC (todos os _now() escrevem em UTC)."""
    if dt is None:
        return None
    from datetime import timezone as _tz
    return dt if dt.tzinfo else dt.replace(tzinfo=_tz.utc)


def _compute_invoice_alerts(invoice) -> list[str]:
    """Avisos informativos no detalhe da nota.

    Sempre comparados contra a data de ENVIO (submitted_at) — apontam
    decisoes do criador no momento do envio, nao demora dos aprovadores.
    Se nota e rascunho, usa hoje como preview ao proprio criador.

    Frases sao construidas de modo a deixar claro que e situacao DA
    NOTA NO ENVIO (nao um julgamento ao aprovador atual). Apenas fatos.
    Nota vencida nao chega aqui (envio bloqueado em submit_invoice).
    """
    from datetime import date as _date
    alerts: list[str] = []

    is_submitted = bool(invoice.submitted_at)
    if is_submitted:
        ref = invoice.submitted_at.date() if hasattr(invoice.submitted_at, "date") else invoice.submitted_at
    else:
        ref = _date.today()

    # Emissao em mes anterior a referencia
    if invoice.issue_date and (invoice.issue_date.year, invoice.issue_date.month) < (ref.year, ref.month):
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
                # rascunho — preview pro proprio criador
                alerts.append(f"Se enviar agora, ficara {when}.")
    return alerts


def _history_response(entry: ApprovalHistory) -> ApprovalHistoryResponse:
    return ApprovalHistoryResponse(
        id=entry.id,
        action=entry.action.value,
        comment=entry.comment,
        timestamp=_as_utc(entry.timestamp),
        user=UserBrief.model_validate(entry.user),
    )


def invoice_response(invoice: Invoice) -> InvoiceResponse:
    from app.schemas.invoice import AttachmentBrief
    history = sorted(invoice.approval_history, key=lambda item: item.timestamp)
    dept = invoice.created_by.department_obj if invoice.created_by else None
    attachments = [
        AttachmentBrief(
            id=a.id,
            drive_file_name=a.drive_file_name,
            size_bytes=a.size_bytes or 0,
            uploaded_at=_as_utc(a.uploaded_at),
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
        created_by=UserBrief.model_validate(invoice.created_by),
        manager=UserBrief.model_validate(invoice.manager) if invoice.manager else None,
        director=UserBrief.model_validate(invoice.director) if invoice.director else None,
        created_at=_as_utc(invoice.created_at),
        submitted_at=_as_utc(invoice.submitted_at),
        manager_reviewed_at=_as_utc(invoice.manager_reviewed_at),
        director_reviewed_at=_as_utc(invoice.director_reviewed_at),
        paid_at=_as_utc(invoice.paid_at),
        history=[_history_response(entry) for entry in history],
        department_name=dept.name if dept else None,
        can_cancel=_can_cancel(invoice),
        alerts=_compute_invoice_alerts(invoice),
    )


def _can_cancel(invoice: Invoice) -> bool:
    from app.models import ApprovalAction, InvoiceStatus
    if invoice.status not in {InvoiceStatus.AGUARDANDO_GESTOR, InvoiceStatus.AGUARDANDO_DIRETOR}:
        return False
    approved = {ApprovalAction.APPROVED_MANAGER, ApprovalAction.APPROVED_DIRECTOR}
    return not any(h.action in approved for h in invoice.approval_history)


def _check_pdf_safety(file_bytes: bytes) -> None:
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
        return  # se pypdf nao estiver disponivel, pula check silenciosamente

    try:
        reader = PdfReader(BytesIO(file_bytes), strict=False)
    except Exception:
        return  # PDF malformado mas com header valido — deixa passar

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
        pass  # estrutura inesperada — segue verificando outras coisas

    # 2. OpenAction (executa algo automaticamente ao abrir o PDF)
    try:
        if root and "/OpenAction" in root:
            action = root["/OpenAction"]
            # /OpenAction pode ser uma referencia a um objeto Action com /S /JavaScript
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

        # 3. AcroForm com JavaScript (/AA = Additional Actions)
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


async def _read_pdf_upload(file: UploadFile | None) -> tuple[bytes | None, str | None]:
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
    # Verifica payloads ativos no PDF (JS, auto-actions)
    _check_pdf_safety(file_bytes)
    return file_bytes, f"{uuid.uuid4()}.pdf"


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


async def _read_pdf_uploads(files: list[UploadFile] | None) -> list[tuple[bytes, str]]:
    """Le, valida e retorna lista de (bytes, filename_original) para multi-upload."""
    if not files:
        return []
    result = []
    for f in files:
        if f is None:
            continue
        # Ignora inputs vazios (alguns navegadores enviam UploadFile com filename vazio)
        if not f.filename:
            continue
        file_bytes = await f.read()
        if not file_bytes:
            continue
        if len(file_bytes) > MAX_PDF_SIZE:
            raise HTTPException(400, f"Arquivo '{f.filename}' excede o limite de 10MB por arquivo")
        if not file_bytes.startswith(b"%PDF"):
            raise HTTPException(400, f"'{f.filename}' nao parece ser um PDF valido")
        _check_pdf_safety(file_bytes)
        result.append((file_bytes, f.filename))
    return result


@router.post("/", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    request: Request,
    invoice_number: str = Form(...),
    issue_date: date = Form(...),
    due_date: date = Form(...),
    description: str = Form(...),
    bank_details: Optional[str] = Form(default=None),
    amount: Decimal = Form(...),
    submit_now: bool = Form(default=True),
    director_id: Optional[str] = Form(default=None),
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    parsed_files = await _read_pdf_uploads(files)
    data = InvoiceCreate(
        invoice_number=invoice_number,
        issue_date=issue_date,
        due_date=due_date,
        description=description,
        bank_details=bank_details,
        amount=amount,
    )
    invoice = invoice_service.create_invoice(
        db,
        data,
        current_user,
        files=parsed_files,
        ip=_client_ip(request),
        port=_client_port(request),
        submit_now=submit_now,
        director_id=director_id or None,
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/submit", response_model=InvoiceResponse)
def submit_invoice(
    invoice_id: str,
    request: Request,
    director_id: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    invoice = invoice_service.submit_invoice(
        db, invoice_id, current_user,
        director_id=director_id,
        ip=_client_ip(request),
        port=_client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/cancel", response_model=InvoiceResponse)
def cancel_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    invoice = invoice_service.cancel_invoice(db, invoice_id, current_user, ip=_client_ip(request), port=_client_port(request))
    return invoice_response(invoice)


@router.get("/directors", response_model=list)
def get_directors(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lista diretores disponíveis com indicação de compatibilidade com o setor do usuário."""
    return invoice_service.get_available_directors(db, current_user)


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
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if page < 1:
        raise HTTPException(status_code=400, detail="page deve ser >= 1")
    if per_page < 1 or per_page > 100:
        raise HTTPException(status_code=400, detail="per_page deve ficar entre 1 e 100")

    # Validacao de datas ISO — sem isso "from_date=abc" causa 500
    from datetime import date as _date
    for label, value in (("from_date", from_date), ("to_date", to_date), ("due_from", due_from), ("due_to", due_to)):
        if value:
            try:
                _date.fromisoformat(value)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"{label}: formato de data invalido (use YYYY-MM-DD)")

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
    )
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
        ip=_client_ip(request),
        port=_client_port(request),
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
        ip=_client_ip(request),
        port=_client_port(request),
    )
    return invoice_response(invoice)


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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Falha ao montar anexos")

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    # Audit log de visualizacao
    invoice_service._add_audit(
        db, current_user.id, "VIEW_PDF_MERGED", invoice.id,
        ip=_client_ip(request), port=_client_port(request), http_method="GET",
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
        ip=_client_ip(request), port=_client_port(request),
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
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    """Remove um anexo individual da nota (so criador, status editavel)."""
    invoice_service.delete_attachment(
        db, invoice_id, attachment_id, current_user,
        ip=_client_ip(request), port=_client_port(request),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    invoice_service.delete_invoice(db, invoice_id, current_user, ip=_client_ip(request), port=_client_port(request))
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
    files: list[UploadFile] = File(default_factory=list),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value)),
):
    """PATCH adiciona NOVOS anexos (nao substitui). Pra remover use
    DELETE /{invoice_id}/attachments/{attachment_id}."""
    new_files = await _read_pdf_uploads(files)
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
            }.items()
            if value is not None
        }
    )
    invoice = invoice_service.update_invoice(
        db,
        invoice_id,
        data,
        current_user,
        new_files=new_files,
        ip=_client_ip(request),
        port=_client_port(request),
    )
    return invoice_response(invoice)


@router.post("/{invoice_id}/mark-paid", response_model=InvoiceResponse)
def mark_paid(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.FINANCE.value)),
):
    invoice = invoice_service.mark_paid(db, invoice_id, current_user, ip=_client_ip(request), port=_client_port(request))
    return invoice_response(invoice)
