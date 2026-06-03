"""Configuracao compartilhada de testes.

Cada teste roda contra um SQLite isolado (arquivo temporario). O modulo
`app.main` e importado lazy depois das env vars serem setadas — sem isso,
`app.config.settings` instancia com SECRET_KEY default e dispara warnings
ou fail-fast indesejado.

Auditoria P2 (testes): essa suite cobre regressoes dos achados P0/P1
implementados. Falha aqui = quebrar producao.
"""
from __future__ import annotations

import os
import secrets
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def _test_env() -> Path:
    """Configura env vars seguras antes de importar o app.

    SECRET_KEY e MASTER_ENCRYPTION_KEY randoms — sem isso, fail-fast em
    PROD (P1-2). Como ENVIRONMENT=DEV, fail-fast nao dispara, mas mantemos
    valores realistas pra exercitar a logica.
    """
    tmpdir = Path(tempfile.mkdtemp(prefix="economart-tests-"))
    db_path = tmpdir / "test.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["SECRET_KEY"] = secrets.token_hex(64)
    os.environ["MASTER_ENCRYPTION_KEY"] = secrets.token_urlsafe(32)
    os.environ["ENVIRONMENT"] = "DEV"
    # Email desligado nos testes — evita tentar enviar de verdade.
    os.environ.setdefault("EMAIL_PROVIDER", "DISABLED")
    # Acelera login: bcrypt e lento, mas vale a pena exercitar com config real.
    yield tmpdir


@pytest.fixture(scope="session")
def app(_test_env):
    """Importa app/main APOS env vars setadas."""
    from app.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def client(app):
    """TestClient do FastAPI — wraps httpx, executa ASGI in-memory.

    Cada teste recebe instancia nova pra evitar leaking de cookies entre
    cenarios. Session/DB compartilhados (mesmo arquivo SQLite) — testes
    devem ser idempotentes ou usar dados isolados.
    """
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c
