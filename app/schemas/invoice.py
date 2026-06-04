from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class UserBrief(BaseModel):
    id: str
    name: str
    # email omitido — minimizacao de dados (LGPD): nao expor e-mail em respostas de nota fiscal
    model_config = {"from_attributes": True}


class InvoiceCreate(BaseModel):
    invoice_number: str = Field(min_length=1, max_length=50)
    issue_date: date
    due_date: date
    description: str = Field(min_length=10, max_length=2000)
    bank_details: Optional[str] = Field(default=None, max_length=500)
    amount: Decimal = Field(gt=0, decimal_places=2)
    supplier_document: str = Field(min_length=11, max_length=18)  # com ou sem mascara
    supplier_name: Optional[str] = Field(default=None, max_length=255)
    supplier_legal_name: Optional[str] = Field(default=None, max_length=255)
    # P1-3 (auditoria): soft-check de duplicidade. Quando o backend detecta
    # outra nota ATIVA com mesmo (supplier_document, invoice_number) ou mesmo
    # criador + numero, devolve 409 com codigo DUPLICATE_INVOICE_NUMBER.
    # Cliente pode reenviar com confirm_duplicate=True para forcar (fornecedor
    # diferente reaproveitando numeracao e legitimo no Brasil).
    confirm_duplicate: bool = False

    @field_validator("due_date")
    @classmethod
    def due_after_issue(cls, v, info):
        if "issue_date" in info.data and v < info.data["issue_date"]:
            raise ValueError("due_date deve ser >= issue_date")
        return v

    @field_validator("supplier_document")
    @classmethod
    def validate_supplier_document(cls, v):
        from app.services.document_service import detect_document_type, strip_non_digits
        doc_type = detect_document_type(v)
        if not doc_type:
            raise ValueError("CPF/CNPJ invalido. Verifique os digitos.")
        return strip_non_digits(v)


class InvoiceUpdate(BaseModel):
    invoice_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    description: Optional[str] = Field(default=None, min_length=10, max_length=2000)
    bank_details: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[Decimal] = Field(default=None, gt=0)
    supplier_document: Optional[str] = Field(default=None, min_length=11, max_length=18)
    supplier_name: Optional[str] = Field(default=None, max_length=255)
    supplier_legal_name: Optional[str] = Field(default=None, max_length=255)
    confirm_duplicate: bool = False  # mesma semantica do create (P1-3 auditoria)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValueError("due_date deve ser >= issue_date")
        return self

    @field_validator("supplier_document")
    @classmethod
    def validate_supplier_document(cls, v):
        if v is None:
            return None
        from app.services.document_service import detect_document_type, strip_non_digits
        doc_type = detect_document_type(v)
        if not doc_type:
            raise ValueError("CPF/CNPJ invalido.")
        return strip_non_digits(v)


class ReviewAction(BaseModel):
    action: str
    comment: Optional[str] = Field(default=None, max_length=1000)

    @field_validator("action")
    @classmethod
    def validate_action(cls, v):
        if v not in ("APPROVE", "REJECT"):
            raise ValueError("action deve ser APPROVE ou REJECT")
        return v

    @field_validator("comment")
    @classmethod
    def comment_required_on_reject(cls, v, info):
        if info.data.get("action") == "REJECT" and (not v or len(v.strip()) < 10):
            raise ValueError("comment e obrigatorio ao reprovar (minimo 10 caracteres)")
        return v


class ApprovalHistoryResponse(BaseModel):
    id: str
    action: str
    comment: Optional[str]
    timestamp: datetime
    user: UserBrief
    model_config = {"from_attributes": True}


class AttachmentBrief(BaseModel):
    id: str
    drive_file_name: Optional[str] = None
    size_bytes: int = 0
    uploaded_at: datetime
    model_config = {"from_attributes": True}


class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    issue_date: date
    due_date: date
    description: str
    bank_details: Optional[str]
    amount: Decimal
    status: str
    has_attachment: bool  # legado — True se tem qualquer anexo
    attachments: list[AttachmentBrief] = []
    # Fornecedor
    supplier_document: Optional[str] = None  # so digitos
    supplier_document_type: Optional[str] = None  # CPF | CNPJ
    supplier_name: Optional[str] = None
    supplier_legal_name: Optional[str] = None
    created_by: UserBrief
    manager: Optional[UserBrief]
    director: Optional[UserBrief]
    created_at: datetime
    submitted_at: Optional[datetime]
    manager_reviewed_at: Optional[datetime]
    director_reviewed_at: Optional[datetime]
    paid_at: Optional[datetime]
    history: list[ApprovalHistoryResponse] = []
    department_name: Optional[str] = None
    can_cancel: bool = False
    # Alertas contextuais (emissao antiga, vencimento curto) — banner no detalhe
    alerts: list[str] = []
    # Contagem de comentarios na thread. Frontend usa pra mostrar badge na
    # lista/drawer sem precisar carregar a thread inteira.
    comments_count: int = 0
    model_config = {"from_attributes": True}


class PaginatedInvoices(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    per_page: int
    pages: int
    total_amount: float = 0.0  # soma de TODOS os itens que batem nos filtros, nao so da pagina atual
