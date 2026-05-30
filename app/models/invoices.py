import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, Date, DateTime, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceStatus(str, enum.Enum):
    RASCUNHO = "RASCUNHO"
    AGUARDANDO_GESTOR = "AGUARDANDO_GESTOR"
    REPROVADO_GESTOR = "REPROVADO_GESTOR"
    AGUARDANDO_DIRETOR = "AGUARDANDO_DIRETOR"
    REPROVADO_DIRETOR = "REPROVADO_DIRETOR"
    APROVADO = "APROVADO"
    PAGO = "PAGO"


class Invoice(Base):
    __tablename__ = "invoices"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_number = Column(String(100), nullable=False)
    issue_date = Column(Date, nullable=False)
    due_date = Column(Date, nullable=False)
    description = Column(Text, nullable=False)
    bank_details = Column(Text, nullable=True)
    amount = Column(Numeric(10, 2), nullable=False)

    status = Column(Enum(InvoiceStatus), default=InvoiceStatus.RASCUNHO, nullable=False)

    created_by_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    manager_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    director_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    finance_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    drive_file_id = Column(String(255), nullable=True)
    drive_file_name = Column(String(255), nullable=True)
    encryption_key_enc = Column(Text, nullable=True)

    created_at = Column(DateTime, default=utc_now, nullable=False)
    submitted_at = Column(DateTime, nullable=True)
    manager_reviewed_at = Column(DateTime, nullable=True)
    director_reviewed_at = Column(DateTime, nullable=True)
    paid_at = Column(DateTime, nullable=True)

    print_drive_file_id = Column(String(255), nullable=True)
    printed_at = Column(DateTime, nullable=True)
    printed_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    # Snapshot da descricao no momento da reprovacao. Reenvio so e permitido
    # se a descricao atual diferir desta — evita reenvio sem alteracao real.
    description_at_rejection = Column(Text, nullable=True)

    # ─── Fornecedor / titular (CPF ou CNPJ) ──────────────────────────────
    # supplier_document armazena apenas digitos (11 = CPF, 14 = CNPJ)
    supplier_document = Column(String(14), nullable=True, index=True)
    # CPF | CNPJ — tipo do documento (derivavel mas economiza queries)
    supplier_document_type = Column(String(4), nullable=True)
    # Nome fantasia (CNPJ) ou nome completo (CPF) — autopreenchido pela API
    supplier_name = Column(String(255), nullable=True)
    # Razao social (so para CNPJ)
    supplier_legal_name = Column(String(255), nullable=True)

    created_by = relationship(
        "User",
        foreign_keys=[created_by_id],
        back_populates="created_invoices",
    )
    manager = relationship("User", foreign_keys=[manager_id])
    director = relationship("User", foreign_keys=[director_id])
    finance = relationship("User", foreign_keys=[finance_id])
    printed_by = relationship("User", foreign_keys=[printed_by_id])
    approval_history = relationship(
        "ApprovalHistory",
        back_populates="invoice",
        cascade="all, delete-orphan",
    )
    attachments = relationship(
        "InvoiceAttachment",
        back_populates="invoice",
        cascade="all, delete-orphan",
        order_by="InvoiceAttachment.uploaded_at",
    )
