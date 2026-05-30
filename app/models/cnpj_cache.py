"""Cache local de consultas ao opencnpj.org (TTL 180 dias)."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String

from app.database import Base


class CnpjCache(Base):
    __tablename__ = "cnpj_cache"

    cnpj = Column(String(14), primary_key=True)  # so digitos
    razao_social = Column(String(255), nullable=True)
    nome_fantasia = Column(String(255), nullable=True)
    cached_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
