import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    action = Column(String(100), nullable=False)
    resource_type = Column(String(100), nullable=True)
    resource_id = Column(String(100), nullable=True)
    ip_address = Column(String(45), nullable=True)   # pseudonimizado via HMAC (LGPD)
    source_port = Column(Integer, nullable=True)       # porta lógica — individualizacao NAT (Marco Civil Art.15)
    http_method = Column(String(10), nullable=True)
    user_agent = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=utc_now, nullable=False)
    success = Column(Boolean, nullable=False)
    detail = Column(Text, nullable=True)

    user = relationship("User")
