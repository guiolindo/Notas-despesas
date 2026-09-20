"""Cobertura de page guards HTML (page_auth.py).

Antes: 28% coverage (Manus/set-2026 audit — QA-04). SEC-20 mora
aqui, entao merece cobertura direta alem dos testes em
test_pentest_regression.
"""
from __future__ import annotations

from tests._helpers import make_user, login_via_http


def test_dashboard_redirects_to_login_when_no_cookie(client):
    """Sem cookie, /dashboard redireciona pra /login."""
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code in (302, 401)
    if r.status_code == 302:
        assert "/login" in r.headers.get("location", "")


def test_dashboard_opens_with_valid_cookie(client):
    """Cookie valido -> dashboard 200."""
    email, pw, _ = make_user(role="EMPLOYEE")
    login_via_http(client, email, pw)
    # login_via_http seta o cookie no client
    r = client.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200


def test_admin_page_forbidden_for_employee(client):
    """/admin/users com cookie de EMPLOYEE -> 403."""
    email, pw, _ = make_user(role="EMPLOYEE")
    login_via_http(client, email, pw)
    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 403


def test_admin_page_ok_for_admin(client):
    """/admin/users com cookie de ADMIN -> 200."""
    email, pw, _ = make_user(role="ADMIN")
    login_via_http(client, email, pw)
    r = client.get("/admin/users", follow_redirects=False)
    assert r.status_code == 200


def test_invalid_cookie_redirects_and_clears(client):
    """Cookie corrompido -> redirect + Set-Cookie limpando refresh_token."""
    r = client.get(
        "/dashboard",
        cookies={"refresh_token": "invalido.corrompido.aqui"},
        follow_redirects=False,
    )
    assert r.status_code == 302
    # Set-Cookie deveria expirar o refresh_token
    set_cookie = r.headers.get("set-cookie", "").lower()
    assert "refresh_token" in set_cookie


def test_page_guard_ignores_bearer_token(client):
    """Page guard so olha cookie, nao Bearer. Bearer sozinho -> redirect."""
    email, pw, _ = make_user(role="ADMIN")
    headers, token = login_via_http(client, email, pw)
    # Limpa cookie e tenta com header apenas
    client.cookies.clear()
    r = client.get("/dashboard", headers={"Authorization": f"Bearer {token}"}, follow_redirects=False)
    assert r.status_code == 302  # sem cookie, redireciona
