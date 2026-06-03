"""P1-7 — health endpoints reais.

Verifica que `/health/live` e `/health/ready` respondem corretamente e
que o middleware de request_id ecoa o header `X-Request-ID`.
"""
from __future__ import annotations


def test_health_live_responds_ok(client):
    """Liveness simples — sempre 200 com {"status":"ok"}.

    Esse endpoint NAO deve consultar DB nem dependencias externas. Mantemos
    isso pra que `_intercept_startup_failure` continue deixando passar mesmo
    com config quebrada.
    """
    resp = client.get("/health/live")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_ready_checks_db(client):
    """Readiness chama SELECT 1 no banco — em DEV/SQLite isso passa."""
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["db"]["ok"] is True


def test_request_id_middleware_echoes(client):
    """Cliente envia X-Request-ID -> server ecoa o mesmo (sanitizado)."""
    rid = "smoketest1234abcd"
    resp = client.get("/health/live", headers={"X-Request-ID": rid})
    assert resp.headers.get("x-request-id") == rid


def test_request_id_middleware_generates_when_absent(client):
    """Sem header, server gera um (12 hex chars).

    Apenas garante que o header existe e tem comprimento razoavel — o valor
    exato e randomico.
    """
    resp = client.get("/health/live")
    rid = resp.headers.get("x-request-id")
    assert rid is not None
    assert 8 <= len(rid) <= 64


def test_request_id_sanitizes_garbage(client):
    """Cliente manda algo invalido (espacos, ; etc.) -> server gera novo."""
    resp = client.get("/health/live", headers={"X-Request-ID": "drop tables; --"})
    rid = resp.headers.get("x-request-id")
    # Deve ter rejeitado o input e gerado novo (sem espacos).
    assert " " not in rid
    assert ";" not in rid
