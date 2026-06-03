"""P2-8 — email retry queue.

Cobre o caminho de enqueue + drain. Nao exercita o SMTP de verdade
(EMAIL_PROVIDER=DISABLED nos testes), so as transicoes de estado.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_enqueue_creates_pending_row(client):
    """enqueue_email() insere row com status PENDING e attempts=0."""
    from sqlalchemy.orm import Session

    from app.database import engine
    from app.models import EmailQueue, EmailStatus
    from app.services.email_queue_service import enqueue_email

    mid = enqueue_email(
        to_email="x@y.z",
        subject="Teste",
        html_body="<p>oi</p>",
        text_body="oi",
        category="test",
    )
    assert isinstance(mid, str) and len(mid) >= 30  # UUID

    with Session(engine) as db:
        row = db.query(EmailQueue).filter_by(id=mid).first()
        assert row is not None
        assert row.status == EmailStatus.PENDING
        assert row.attempts == 0
        assert row.category == "test"


def test_drain_marks_failed_after_max_attempts(client, monkeypatch):
    """Drain com provedor que sempre falha -> apos max_attempts vira FAILED."""
    import app.services.email_queue_service as eqs
    from app.database import engine
    from app.models import EmailQueue, EmailStatus
    from sqlalchemy.orm import Session

    # Mock do provedor: sempre falha
    monkeypatch.setattr(
        eqs, "_try_send", lambda row: (False, "fake provider down"),
    )

    mid = eqs.enqueue_email(
        to_email="fail@example.com", subject="x", html_body="<p>x</p>",
        category="drain-test-fail",
    )

    # Acelera o backoff: marca next_retry_at no passado pra cada drain.
    for _ in range(5):  # max_attempts default = 4, mais um pra confirmar
        with Session(engine) as db:
            row = db.query(EmailQueue).filter_by(id=mid).first()
            if row is None:
                break
            row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            db.commit()
        eqs.drain_email_queue(limit=10)

    with Session(engine) as db:
        row = db.query(EmailQueue).filter_by(id=mid).first()
        assert row.status == EmailStatus.FAILED
        assert row.attempts >= 4
        assert "fake provider down" in (row.last_error or "")


def test_drain_marks_sent_on_success(client, monkeypatch):
    """Drain com provedor que retorna sucesso -> status SENT."""
    import app.services.email_queue_service as eqs
    from app.database import engine
    from app.models import EmailQueue, EmailStatus
    from sqlalchemy.orm import Session

    monkeypatch.setattr(eqs, "_try_send", lambda row: (True, None))

    mid = eqs.enqueue_email(
        to_email="ok@example.com", subject="x", html_body="<p>x</p>",
        category="drain-test-ok",
    )

    # Marca next_retry_at no passado pra drain pegar agora
    with Session(engine) as db:
        row = db.query(EmailQueue).filter_by(id=mid).first()
        row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()

    sent, failed, retried = eqs.drain_email_queue(limit=10)
    assert sent >= 1

    with Session(engine) as db:
        row = db.query(EmailQueue).filter_by(id=mid).first()
        assert row.status == EmailStatus.SENT
        assert row.sent_at is not None
