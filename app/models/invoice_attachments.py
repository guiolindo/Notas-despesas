"""Anexos da nota fiscal.

Uma nota pode ter ate 5 PDFs (nota + boleto + comprovantes extras).
Cada anexo:
- Criptografado individualmente com Fernet (key armazenada cifrada com MASTER)
- Tem nome original preservado (sanitizado) para identificacao na UI
- Ordem de exibicao = ordem de upload (timestamp)
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceAttachment(Base):
    __tablename__ = "invoice_attachments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = Column(
        String(36),
        ForeignKey("invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    drive_file_id = Column(String(255), nullable=False)
    drive_file_name = Column(String(255), nullable=True)
    encryption_key_enc = Column(Text, nullable=False)
    size_bytes = Column(Integer, nullable=False, default=0)
    uploaded_at = Column(DateTime, default=utc_now, nullable=False)
    uploaded_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    invoice = relationship("Invoice", back_populates="attachments")
