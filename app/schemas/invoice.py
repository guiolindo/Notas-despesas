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

    @field_validator("due_date")
    @classmethod
    def due_after_issue(cls, v, info):
        if "issue_date" in info.data and v < info.data["issue_date"]:
            raise ValueError("due_date deve ser >= issue_date")
        return v


class InvoiceUpdate(BaseModel):
    invoice_number: Optional[str] = Field(default=None, min_length=1, max_length=50)
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    description: Optional[str] = Field(default=None, min_length=10, max_length=2000)
    bank_details: Optional[str] = Field(default=None, max_length=500)
    amount: Optional[Decimal] = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.issue_date and self.due_date and self.due_date < self.issue_date:
            raise ValueError("due_date deve ser >= issue_date")
        return self


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


class InvoiceResponse(BaseModel):
    id: str
    invoice_number: str
    issue_date: date
    due_date: date
    description: str
    bank_details: Optional[str]
    amount: Decimal
    status: str
    has_attachment: bool
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
    model_config = {"from_attributes": True}


class PaginatedInvoices(BaseModel):
    items: list[InvoiceResponse]
    total: int
    page: int
    per_page: int
    pages: int
