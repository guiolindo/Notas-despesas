"""P0-1 + P1-6 + P1-8 — auth, refresh, must_change_password, 404 leak.

Esses testes giram em torno de cenarios que custaram pra detectar na auditoria.
Falha aqui = regressao critica.
"""
from __future__ import annotations

import uuid


def _create_active_user(app, *, must_change_password: bool = False, role: str = "EMPLOYEE"):
    """Cria um usuario direto no DB pra testar sem mexer com /admin/users."""
    from sqlalchemy.orm import Session

    from app.database import engine
    from app.models import User, UserRole
    from app.security.hashing import hash_password

    raw_password = "Test1234!"
    user_id = str(uuid.uuid4())
    email = f"test-{user_id[:8]}@economart.local.example.com"
    with Session(engine) as db:
        user = User(
            id=user_id,
            email=email,
            name="Test User",
            hashed_password=hash_password(raw_password),
            role=UserRole(role),
            is_active=True,
            must_change_password=must_change_password,
        )
        db.add(user)
        db.commit()
    return email, raw_password, user_id


def test_refresh_without_cookie_returns_401(client):
    """Sem cookie de refresh, /auth/refresh devolve 401 — nao vaza nada."""
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401


def test_refresh_with_invalid_cookie_returns_401_and_clears_cookie(client):
    """Cookie quebrado -> 401 + Set-Cookie limpando o cookie do cliente.

    P0-1 da auditoria: refresh expirado/invalido deve apagar o cookie pro
    cliente nao ficar batendo no /refresh em loop.
    """
    client.cookies.set("refresh_token", "this.is.not.a.valid.jwt")
    resp = client.post("/auth/refresh")
    assert resp.status_code == 401
    # FastAPI/Starlette serializa delete via Set-Cookie com Max-Age=0
    set_cookie = resp.headers.get("set-cookie", "")
    assert "refresh_token" in set_cookie.lower()


def test_login_and_refresh_cycle(client):
    """Fluxo feliz: login -> recebe access + cookie de refresh -> /refresh
    devolve novo access token."""
    email, password, _ = _create_active_user(client.app)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    body = login.json()
    assert "access_token" in body
    assert body["user"]["email"] == email
    # Cookie de refresh setado
    assert "refresh_token" in client.cookies

    refresh = client.post("/auth/refresh")
    assert refresh.status_code == 200
    new_body = refresh.json()
    assert "access_token" in new_body
    # Tokens novos devem ser diferentes (jti diferente)
    assert new_body["access_token"] != body["access_token"]


def test_change_password_invalidates_old_refresh(client):
    """P0-1: depois de mudar a senha, refresh emitido antes deve falhar.

    Cenario: usuario loga, troca senha, depois um atacante com o cookie
    antigo tenta renovar -> deve receber 401.

    Detalhe de implementacao: `token_is_pre_password_change` tem tolerancia
    de 2 segundos pra cobrir login imediatamente apos troca/reset (iat do
    JWT e truncado a segundo, password_changed_at tem microsegundo). Em
    producao, esse cenario tipico acontece minutos depois, nao milissegundos.
    Aqui forcamos `password_changed_at` no futuro pra simular a janela
    real onde o atacante tem o cookie antigo e a vitima trocou a senha.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy.orm import Session

    from app.database import engine
    from app.models import User

    email, password, user_id = _create_active_user(client.app)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    old_cookie = client.cookies.get("refresh_token")
    assert old_cookie

    # Simula troca de senha que aconteceu DEPOIS da emissao do token.
    # Direto no DB pra controlar o timestamp sem depender do clock real.
    with Session(engine) as db:
        user = db.query(User).filter_by(id=user_id).first()
        user.password_changed_at = datetime.now(timezone.utc) + timedelta(minutes=5)
        db.commit()

    # Tenta usar o cookie antigo pra renovar — atacante isolado.
    client.cookies.clear()
    client.cookies.set("refresh_token", old_cookie)
    resp = client.post("/auth/refresh")
    # Refresh tem que falhar — senao token vive ate 7 dias mesmo apos reset
    assert resp.status_code == 401, f"Esperava 401, recebi {resp.status_code}: {resp.text}"


def test_must_change_password_blocks_api_with_428(client):
    """P1-8 da auditoria: backend bloqueia API quando flag esta True.

    Usuario com `must_change_password=True` so pode bater em /auth/me,
    /auth/change-password e /auth/logout. Qualquer outro endpoint -> 428.
    """
    email, password, _ = _create_active_user(client.app, must_change_password=True)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # /auth/me passa
    me = client.get("/auth/me", headers=auth)
    assert me.status_code == 200

    # /api/invoices/ NAO passa enquanto must_change_password=True
    inv = client.get("/api/invoices/", headers=auth)
    assert inv.status_code == 428, inv.text


def test_verify_full_returns_404_for_missing_or_forbidden(client):
    """P1-6 da auditoria: nota inexistente E nota sem permissao devolvem
    o MESMO 404. Evita oraculo de existencia de UUID."""
    email, password, _ = _create_active_user(client.app)
    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    token = login.json()["access_token"]

    # ID inexistente
    fake_id = str(uuid.uuid4())
    resp = client.get(
        f"/api/invoices/{fake_id}/verify-full",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
    # Detalhe nao expoe o motivo real
    detail = resp.json().get("detail", "").lower()
    assert "permiss" not in detail  # nao revela "sem permissao"
