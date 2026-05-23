import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalAction(str, enum.Enum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"
    APPROVED_MANAGER = "APPROVED_MANAGER"
    REJECTED_MANAGER = "REJECTED_MANAGER"
    APPROVED_DIRECTOR = "APPROVED_DIRECTOR"
    REJECTED_DIRECTOR = "REJECTED_DIRECTOR"
    MARKED_PAID = "MARKED_PAID"
    PRINTED = "PRINTED"


class ApprovalHistory(Base):
    __tablename__ = "approval_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    action = Column(Enum(ApprovalAction), nullable=False)
    comment = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    ip_address = Column(String(45), nullable=True)   # pseudonimizado via HMAC (LGPD)
    source_port = Column(Integer, nullable=True)       # porta lógica — individualizacao NAT

    invoice = relationship("Invoice", back_populates="approval_history")
    user = relationship("User")
