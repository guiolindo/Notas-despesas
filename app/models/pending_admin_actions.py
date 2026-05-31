"""Acoes administrativas com janela de tolerancia de 24h.

Quando um admin solicita acao sensivel em conta de diretor (desativar,
encerrar, redefinir senha), o sistema NAO executa imediatamente. Cria
um pendente, avisa o alvo + outros diretores, e so executa apos
GRACE_PERIOD_HOURS sem contestacao.

Permite que um diretor real possa cancelar uma acao indevida feita por
um admin malicioso ou enganado.
"""
import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import relationship

from app.database import Base


GRACE_PERIOD_HOURS = 24


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class PendingActionType(str, enum.Enum):
    DEACTIVATE_DIRECTOR = "DEACTIVATE_DIRECTOR"
    ENCERRAR_DIRECTOR = "ENCERRAR_DIRECTOR"
    RESET_PASSWORD_DIRECTOR = "RESET_PASSWORD_DIRECTOR"


class PendingActionStatus(str, enum.Enum):
    PENDING = "PENDING"
    CANCELLED = "CANCELLED"
    EXECUTED = "EXECUTED"


class PendingAdminAction(Base):
    __tablename__ = "pending_admin_actions"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    action_type = Column(Enum(PendingActionType), nullable=False)
    target_user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    requested_by_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    requested_at = Column(DateTime, default=_utc_now, nullable=False)
    effective_at = Column(DateTime, nullable=False)
    status = Column(
        Enum(PendingActionStatus),
        default=PendingActionStatus.PENDING,
        nullable=False,
        index=True,
    )
    reason = Column(Text, nullable=True)  # motivo do admin ao solicitar
    # Quando uma acao e cancelada, registra quem e quando (target ou outro diretor)
    cancelled_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    cancel_reason = Column(Text, nullable=True)
    executed_at = Column(DateTime, nullable=True)
    # Payload extra (ex: nova senha em RESET_PASSWORD_DIRECTOR — guardada
    # hasheada no campo password_hash). Mantemos opcional pra futuras acoes.
    extra = Column(Text, nullable=True)  # JSON serializado se precisar

    target = relationship("User", foreign_keys=[target_user_id])
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    cancelled_by = relationship("User", foreign_keys=[cancelled_by_id])
