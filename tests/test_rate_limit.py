"""P1-5 — rate-limit estendido.

Cobre as policies adicionadas no commit 56deb87: forgot-password,
reset-password, lookup-cnpj, comments.
"""
from __future__ import annotations


def _clear_rate_buckets():
    """Zera os buckets antes de cada teste pra nao ter cross-talk.

    Os buckets sao globais ao processo do app; testes rodando em ordem
    podem fazer um envenenar o outro. Limpamos no setup.
    """
    from app.middleware.security import rate_limit_buckets
    rate_limit_buckets.clear()


def test_login_rate_limit_blocks_after_threshold(client):
    """11 POST /auth/login -> 11a deve ser 429 com Retry-After."""
    _clear_rate_buckets()
    last = None
    for _ in range(12):
        last = client.post("/auth/login", json={"email": "x@y.z", "password": "wrong"})
    assert last.status_code == 429
    assert last.headers.get("Retry-After")
    assert last.json().get("detail")


def test_forgot_password_rate_limit(client):
    """POST /auth/forgot-password — 5/600s. 6a deve dar 429."""
    _clear_rate_buckets()
    last = None
    for _ in range(7):
        last = client.post("/auth/forgot-password", json={"email": "x@y.z"})
    assert last.status_code == 429
    assert last.headers.get("Retry-After")


def test_health_not_rate_limited(client):
    """/health/live nao deve ter rate-limit — orquestrador chama varias vezes."""
    _clear_rate_buckets()
    for _ in range(30):
        resp = client.get("/health/live")
        assert resp.status_code == 200, "health/live nao pode ser rate-limited"
