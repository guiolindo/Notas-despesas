"""Cobertura do IdempotencyMiddleware (BE-06)."""
from __future__ import annotations

import uuid
from tests._helpers import make_user, login


def test_idempotency_replay_returns_same_body(client):
    """Mesma Idempotency-Key -> segunda chamada retorna corpo cacheado
    com header X-Idempotent-Replay."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)
    key = str(uuid.uuid4())
    # Primeiro POST /auth/logout com a chave
    r1 = client.post(
        "/auth/logout",
        headers={**headers, "Idempotency-Key": key},
    )
    assert r1.status_code == 200
    body1 = r1.content
    # Segundo com mesma chave — deve replay o body sem revalidar token
    # (que ja foi invalidado). Se replay funcionar, ainda retorna 200.
    r2 = client.post(
        "/auth/logout",
        headers={**headers, "Idempotency-Key": key},
    )
    assert r2.status_code == 200
    assert r2.headers.get("X-Idempotent-Replay") == "true"
    # Corpo (nao comparamos bytes brutos porque gzip middleware pode ter
    # comprimido r2 e nao r1) — verificamos JSON decodificado.
    assert r2.json() == r1.json()


def test_no_idempotency_key_normal_behavior(client):
    """Sem header -> comportamento normal (nao replay)."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)
    r1 = client.post("/auth/logout", headers=headers)
    assert r1.status_code == 200
    assert r1.headers.get("X-Idempotent-Replay") is None
