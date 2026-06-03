"""Fila persistente de emails com retry exponencial.

P2-8 da auditoria: antes, send_email_async usava threading.Thread daemon
fire-and-forget. Se o worker do gunicorn reiniciava no meio do envio (deploy,
OOM, restart), o email se perdia silenciosamente. Notificacoes operacionais
mais ou menos toleravel; codigos de reset de senha NAO.

Esta tabela acumula as mensagens. Um worker drena periodicamente, marcando
SENT em sucesso ou aumentando attempts + next_retry_at em falha. Para
salvaguarda final, FAILED quando esgota max_attempts — admin pode
re-enfileirar manualmente.

Decisao deliberada: NAO usar Celery/RQ — overhead de infra (Redis, worker
dedicado, supervisao) nao se justifica pro volume atual (~poucos emails/dia).
O worker roda dentro do proprio processo via BackgroundTasks/asyncio loop;
sobrevive a restart porque o estado vive no PG, nao em memoria.
"""
import enum
import uuid

from sqlalchemy import (
    Column,
    DateTime,
    Enum,
    Integer,
    Index,
    String,
    Text,
)

from app.database import Base
from app.models.invoices import utc_now


class EmailStatus(str, enum.Enum):
    PENDING = "PENDING"   # aguardando envio (criado ou agendado pra retry)
    SENT = "SENT"         # confirmado pelo provedor (SMTP 250 ou Resend 202)
    FAILED = "FAILED"     # esgotou max_attempts — desistiu


class EmailQueue(Base):
    __tablename__ = "email_queue"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    to_email = Column(String(320), nullable=False)  # 320 = RFC 5321 maximo
    subject = Column(String(500), nullable=False)
    html_body = Column(Text, nullable=False)
    text_body = Column(Text, nullable=True)

    # PENDING -> SENT (sucesso) ou FAILED (esgotou).
    status = Column(Enum(EmailStatus), default=EmailStatus.PENDING, nullable=False, index=True)

    # Backoff exponencial: 1min, 4min, 16min, 64min (=~1h), depois FAILED.
    attempts = Column(Integer, default=0, nullable=False)
    max_attempts = Column(Integer, default=4, nullable=False)

    # Quando esta msg pode voltar a ser tentada. Worker filtra
    # status=PENDING AND next_retry_at <= now. Sem este campo, falhas em
    # serie acumulariam queue infinita de retries imediatos.
    next_retry_at = Column(DateTime, default=utc_now, nullable=False)
    last_error = Column(Text, nullable=True)  # ultima mensagem de erro pra debug

    # Marcador de processamento em curso. Tomado por advisory lock no
    # SELECT FOR UPDATE SKIP LOCKED do worker — evita 2 workers pegarem
    # a mesma msg. Manter ate sucesso/failure final.
    locked_at = Column(DateTime, nullable=True)
    locked_by = Column(String(64), nullable=True)  # pid:hostname pra debug

    created_at = Column(DateTime, default=utc_now, nullable=False)
    sent_at = Column(DateTime, nullable=True)

    # Categoria livre — util pra metricas e debug. Ex: 'reset_password',
    # 'invoice_approval_notify'. NAO usado pra logica.
    category = Column(String(64), nullable=True, index=True)

    __table_args__ = (
        # Worker faz WHERE status=PENDING AND next_retry_at <= now ORDER BY
        # next_retry_at ASC LIMIT N. Este indice cobre o predicado mais o
        # ORDER BY sem extra sort.
        Index("ix_email_queue_pending_retry", "status", "next_retry_at"),
    )
