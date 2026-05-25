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
    """Avisos puramente informativos no detalhe da nota.

    Comparacao contra a data de ENVIO (submitted_at). Se nota e rascunho,
    usa hoje como preview. Sem linguagem de julgamento — apenas fatos.
    Nota vencida nao chega aqui (envio bloqueado em submit_invoice).
    """
    from datetime import date as _date
    alerts: list[str] = []

    if invoice.submitted_at:
        ref = invoice.submitted_at.date() if hasattr(invoice.submitted_at, "date") else invoice.submitted_at
    else:
        ref = _date.today()

    # Emissao em mes anterior a referencia
    if invoice.issue_date and (invoice.issue_date.year, invoice.issue_date.month) < (ref.year, ref.month):
        alerts.append("Data de emissao em mes anterior ao envio.")

    # Vencimento dentro de 72h da data de envio
    if invoice.due_date:
        delta = (invoice.due_date - ref).days
        if 0 <= delta < 3:
            label = "hoje" if delta == 0 else f"em {delta} dia(s)"
            alerts.append(f"Vencimento {label} — prazo curto para aprovacao.")
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
    history = sorted(invoice.approval_history, key=lambda item: item.timestamp)
    dept = invoice.created_by.department_obj if invoice.created_by else None
    return InvoiceResponse(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        issue_date=invoice.issue_date,
        due_date=invoice.due_date,
        description=invoice.description,
        bank_details=invoice.bank_details,
        amount=invoice.amount,
        status=invoice.status.value,
        has_attachment=bool(invoice.drive_file_id),
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
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value, UserRole.MANAGER.value)),
):
    file_bytes, filename = await _read_pdf_upload(file)
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
        file_bytes=file_bytes,
        filename=filename,
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
def get_attachment(
    invoice_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    invoice = invoice_service.get_invoice_or_403(db, invoice_id, current_user)
    pdf_bytes = invoice_service.get_attachment(db, invoice_id, current_user, ip=_client_ip(request), port=_client_port(request))
    filename = f"nota_{invoice.invoice_number}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


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
    file: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_role(UserRole.EMPLOYEE.value)),
):
    file_bytes, filename = await _read_pdf_upload(file)
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
        file_bytes=file_bytes,
        filename=filename,
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
