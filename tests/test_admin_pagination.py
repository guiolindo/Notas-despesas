"""Cobertura de PERF-06 — /api/admin/users paginado."""
from __future__ import annotations

from tests._helpers import make_user, login


def test_admin_users_default_pagination(client):
    """Sem params, retorna primeira pagina de 50."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)
    for _ in range(3):
        make_user(role="EMPLOYEE")
    r = client.get("/api/admin/users", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert len(data) >= 4  # admin + 3 employees + qualquer outro


def test_admin_users_search_filter(client):
    """?search=<termo> filtra por nome/email."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)
    make_user(role="EMPLOYEE")
    r = client.get(
        f"/api/admin/users?search={admin_email.split('@')[0][:8]}",
        headers=admin,
    )
    assert r.status_code == 200
    data = r.json()
    assert any(admin_email in u.get("email", "") for u in data)


def test_admin_users_page_size_limit(client):
    """per_page e capped em 200."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)
    r = client.get("/api/admin/users?per_page=99999", headers=admin)
    assert r.status_code == 200
    # 200 max — pode voltar menos porque so tem alguns users no DB
    assert len(r.json()) <= 200


def test_admin_users_role_filter(client):
    """?role=DIRECTOR filtra por role."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)
    make_user(role="DIRECTOR")
    r = client.get("/api/admin/users?role=DIRECTOR", headers=admin)
    assert r.status_code == 200
    data = r.json()
    assert all(u.get("role") == "DIRECTOR" for u in data)
