import hashlib
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, event
from sqlalchemy.orm import relationship

from app.database import Base


GENESIS_HASH = "0" * 64  # marcador da primeira linha (sem antecessor)


def compute_row_hash(prev_hash: str, row: "AuditLog") -> str:
    """SHA-256 sobre os campos canonicos da linha + hash da anterior.
    Qualquer mudanca em qualquer um desses campos quebra a cadeia.

    Normaliza timestamp pra UTC ingenuo (sem tzinfo) porque o roundtrip
    pelo DB descarta a timezone — sem isso, o hash do insert e o hash da
    verificacao divergem por causa do ' +00:00' que a serializacao perde.
    """
    if row.timestamp is None:
        ts = ""
    else:
        t = row.timestamp
        if t.tzinfo is not None:
            t = t.astimezone(timezone.utc).replace(tzinfo=None)
        ts = t.isoformat()
    parts = [
        prev_hash or GENESIS_HASH,
        row.id or "",
        row.user_id or "",
        row.action or "",
        row.resource_type or "",
        row.resource_id or "",
        row.ip_address or "",
        str(row.source_port) if row.source_port is not None else "",
        row.http_method or "",
        row.user_agent or "",
        ts,
        "1" if row.success else "0",
        row.detail or "",
    ]
    payload = "|".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    # SET NULL preserva o audit_log mesmo se o usuario sumir fisicamente.
    # Hoje sistema usa anonimizacao, mas o constraint protege (P2-9 auditoria).
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
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
    # ── Hash chain (tamper detection) ─────────────────────────────────
    # Cada linha contem o SHA-256 da linha anterior + dos seus proprios
    # campos. Edicao retroativa quebra a cadeia: recalcular o hash da
    # linha modificada da diferente, e todas as linhas POSTERIORES tornam-se
    # invalidas. Detectavel pelo endpoint /api/admin/audit-logs/verify.
    prev_hash = Column(String(64), nullable=True)
    row_hash = Column(String(64), nullable=True)

    user = relationship("User")


def attach_audit_chain_listener(SessionClass) -> None:
    """Attach um listener before_flush na Session que computa prev/row_hash
    para todos os AuditLog novos da flush, em ordem cronologica. Faz isso
    em batch para que multiplas insercoes na mesma transacao sejam
    encadeadas corretamente entre si (e nao todas apontando pra mesma
    linha previa do DB).

    Chamado em main.py apos a definicao de SessionLocal.
    """
    @event.listens_for(SessionClass, "before_flush")
    def _audit_chain_before_flush(session, _flush_context, _instances):
        pending = [obj for obj in session.new if isinstance(obj, AuditLog)]
        if not pending:
            return
        # Garante timestamps + ordena cronologicamente. Linhas sem ts
        # ainda definido recebem agora; manter ordem de criacao via id.
        now = datetime.now(timezone.utc)
        for obj in pending:
            if obj.timestamp is None:
                obj.timestamp = now
        pending.sort(key=lambda o: (o.timestamp, o.id or ""))
        # Le o ultimo row_hash ja COMMITED do banco como ancora da cadeia
        last_db = (
            session.query(AuditLog)
            .order_by(AuditLog.timestamp.desc(), AuditLog.id.desc())
            .first()
        )
        prev = (last_db.row_hash if last_db and last_db.row_hash else GENESIS_HASH)
        for obj in pending:
            obj.prev_hash = prev
            obj.row_hash = compute_row_hash(prev, obj)
            prev = obj.row_hash
