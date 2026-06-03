"""Enfileiramento + worker da fila de emails.

P2-8 da auditoria. Veja docstring de app/models/email_queue.py.

API publica:
- enqueue_email(to, subject, html, text, category=None) -> id da row
- drain_email_queue(limit) -> (sent, failed, retried)  # invocado pelo worker
- start_background_worker(loop_seconds=15) -> Task asyncio que roda forever

Estrategia:
- enqueue() so insere no banco e devolve. Nao chama o provedor — quem
  decide quando enviar e o worker. Isso desacopla request HTTP de I/O lento.
- worker pega ate `limit` mensagens com FOR UPDATE SKIP LOCKED (em PG),
  tenta enviar, atualiza status. SQLite cai pra UPDATE simples (sem race
  porque em DEV e single-process).
- Backoff exponencial: 1, 4, 16, 64 minutos. Apos esgotar attempts, marca
  FAILED — admin precisa reenfileirar manualmente. Dashboard de status
  pode ser adicionado depois (fora deste batch).
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models import EmailQueue, EmailStatus


logger = logging.getLogger("app.email_queue")

# Backoff em minutos por tentativa (indice = attempts ja gastas).
# Index 0 = ainda nao tentou; 4 = ultima chance antes de FAILED.
_BACKOFF_MINUTES = (0, 1, 4, 16, 64)

# Lock stale: se uma row ficou locked_at por mais que isso sem progresso,
# liberamos. Cobre cenario de worker que crashou no meio.
_LOCK_STALE_MINUTES = 5

_WORKER_ID = f"{os.getpid()}:{socket.gethostname()[:20]}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def enqueue_email(
    to_email: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
    category: str | None = None,
    max_attempts: int = 4,
    db: Session | None = None,
) -> str:
    """Insere msg na fila. Devolve o id. NAO envia — worker faz isso.

    Aceita uma Session externa pra participar da mesma transacao do caller
    (ex: enfileirar dentro do mesmo commit que cria a nota). Sem session,
    abre uma sozinha e commita.
    """
    row = EmailQueue(
        to_email=to_email,
        subject=subject,
        html_body=html_body,
        text_body=text_body,
        category=category,
        max_attempts=max_attempts,
        status=EmailStatus.PENDING,
        next_retry_at=_utc_now(),
    )
    if db is not None:
        db.add(row)
        db.flush()
        return row.id
    with SessionLocal() as session:
        session.add(row)
        session.commit()
        session.refresh(row)
        return row.id


def _release_stale_locks(session: Session) -> None:
    """Libera linhas que ficaram lockadas alem do limite. Sem isso, worker
    que crashou no meio do envio deixa o email travado pra sempre."""
    cutoff = _utc_now() - timedelta(minutes=_LOCK_STALE_MINUTES)
    session.execute(
        update(EmailQueue)
        .where(EmailQueue.status == EmailStatus.PENDING)
        .where(EmailQueue.locked_at.isnot(None))
        .where(EmailQueue.locked_at < cutoff)
        .values(locked_at=None, locked_by=None)
    )


def _claim_batch(session: Session, limit: int) -> list[EmailQueue]:
    """Toma um lote de mensagens prontas. Em PG usa SKIP LOCKED pra que 2
    workers nao peguem a mesma row; SQLite roda em DEV (sem concorrencia)."""
    now = _utc_now()
    query = (
        session.query(EmailQueue)
        .filter(EmailQueue.status == EmailStatus.PENDING)
        .filter(EmailQueue.locked_at.is_(None))
        .filter(EmailQueue.next_retry_at <= now)
        .order_by(EmailQueue.next_retry_at.asc())
        .limit(limit)
    )
    if engine.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)
    rows = query.all()
    for row in rows:
        row.locked_at = now
        row.locked_by = _WORKER_ID
    session.flush()
    return rows


def _try_send(row: EmailQueue) -> tuple[bool, str | None]:
    """Chama o provedor real. Retorna (success, error_message_curto)."""
    # Import local pra evitar ciclo (email_service importa enqueue futuramente)
    from app.services.email_service import send_email
    try:
        ok = send_email(
            None,  # SMTP settings legacy parametro — ignorado, usa env
            row.to_email,
            row.subject,
            row.html_body,
            row.text_body,
        )
        return bool(ok), None if ok else "provider returned False"
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)[:500]


def _schedule_retry(row: EmailQueue, error: str | None) -> None:
    """Decide retry vs FAILED, atualiza campos."""
    row.attempts += 1
    row.last_error = error
    row.locked_at = None
    row.locked_by = None
    if row.attempts >= row.max_attempts:
        row.status = EmailStatus.FAILED
        logger.error(
            "[email-queue] FAILED apos %d tentativas: to=%s subj=%r err=%s",
            row.attempts, row.to_email, row.subject[:60], error,
        )
        return
    # Backoff: pega o proximo intervalo. Se acabar a tabela, repete o ultimo.
    minutes = _BACKOFF_MINUTES[min(row.attempts, len(_BACKOFF_MINUTES) - 1)]
    row.next_retry_at = _utc_now() + timedelta(minutes=minutes)
    logger.warning(
        "[email-queue] retry %d/%d em %dmin: to=%s err=%s",
        row.attempts, row.max_attempts, minutes, row.to_email, error,
    )


def drain_email_queue(limit: int = 25) -> tuple[int, int, int]:
    """Processa ate `limit` mensagens. Retorna (sent, failed, retried)
    pra metricas/logs. Cada msg em try/except — uma quebrada nao derruba
    o batch.

    sent     = entregou ao provedor com sucesso
    failed   = esgotou max_attempts neste drain
    retried  = falhou mas vai tentar de novo
    """
    sent = failed = retried = 0
    with SessionLocal() as session:
        _release_stale_locks(session)
        session.commit()  # libera locks antes do claim, sem segurar lock-table

        rows = _claim_batch(session, limit)
        session.commit()  # confirma o claim — outros workers nao pegam de novo

        for row in rows:
            ok, err = _try_send(row)
            if ok:
                row.status = EmailStatus.SENT
                row.sent_at = _utc_now()
                row.locked_at = None
                row.locked_by = None
                row.last_error = None
                sent += 1
            else:
                _schedule_retry(row, err)
                if row.status == EmailStatus.FAILED:
                    failed += 1
                else:
                    retried += 1
            session.commit()
    return sent, failed, retried


# ─── Worker em background ─────────────────────────────────────────────────

_worker_task: asyncio.Task | None = None


async def _worker_loop(interval_seconds: int) -> None:
    """Roda forever drenando a fila. Cada falha do loop e logada mas o
    loop nao morre — drain individual ja captura excecoes por row."""
    logger.info("[email-queue] worker iniciado (interval=%ds, id=%s)", interval_seconds, _WORKER_ID)
    while True:
        try:
            sent, failed, retried = await asyncio.to_thread(drain_email_queue, 25)
            if sent or failed or retried:
                logger.info(
                    "[email-queue] drain: sent=%d failed=%d retried=%d",
                    sent, failed, retried,
                )
        except Exception as exc:  # noqa: BLE001
            logger.error("[email-queue] drain crashou: %s", exc, exc_info=True)
        await asyncio.sleep(interval_seconds)


def start_background_worker(interval_seconds: int = 15) -> None:
    """Inicia o worker assincrono se ainda nao estiver rodando. Idempotente.

    Chamar de app.main no startup. Com gunicorn -w N, cada worker do gunicorn
    inicia o proprio loop — SKIP LOCKED garante que nao peguem a mesma row.
    """
    global _worker_task
    if _worker_task is not None and not _worker_task.done():
        return
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    _worker_task = loop.create_task(_worker_loop(interval_seconds))
