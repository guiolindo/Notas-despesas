"""Comentarios assincronos numa nota.

Diferente do approval_history (que registra acoes do fluxo), os
comentarios sao livres: criador, gestor, diretor e financeiro
conversam pra esclarecer duvidas sem precisar reprovar/reenviar.

Sao imutaveis: nao podem ser editados nem apagados — viram parte da
auditoria. Quem precisa corrigir, manda um novo comentario.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class InvoiceComment(Base):
    __tablename__ = "invoice_comments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    invoice_id = Column(String(36), ForeignKey("invoices.id"), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    body = Column(Text, nullable=False)
    created_at = Column(DateTime, default=_utc_now, nullable=False)

    invoice = relationship("Invoice")
    user = relationship("User")
