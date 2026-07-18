"""Isolamento cross-departamento (IDOR).

Attacker de outro setor nao pode ler, editar, deletar, comentar ou baixar
anexos de nota alheia. Confirmado no pentest jun/2026 — agora com
regressao automatica.
"""
from __future__ import annotations

from tests._helpers import (
    create_full_department_users,
    create_invoice,
    invoice_payload,
    login,
    make_department,
    make_user,
)


def _setup_two_departments():
    """Retorna (victim_ctx, attacker_email, attacker_pw) com attacker em outro dept."""
    victim_ctx = create_full_department_users()
    other_dept = make_department()  # nome default -> unico via uuid
    att_email, att_pw, _ = make_user(role="EMPLOYEE", department_id=other_dept)
    return victim_ctx, att_email, att_pw


def test_attacker_cannot_view_victims_invoice(client):
    """GET /api/invoices/{id} da victim -> 403 pro attacker."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.get(f"/api/invoices/{inv['id']}", headers=attacker)
    assert r.status_code == 403


def test_attacker_cannot_edit_victims_invoice(client):
    """PATCH da victim -> 403."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.patch(
        f"/api/invoices/{inv['id']}",
        headers=attacker,
        data={"amount": "999999"},
    )
    assert r.status_code == 403


def test_attacker_cannot_delete_victims_invoice(client):
    """DELETE da victim -> 403."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.delete(f"/api/invoices/{inv['id']}", headers=attacker)
    assert r.status_code == 403


def test_attacker_cannot_submit_victims_invoice(client):
    """POST /submit da victim -> 403."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.post(f"/api/invoices/{inv['id']}/submit", headers=attacker)
    assert r.status_code == 403


def test_attacker_cannot_read_victims_comments(client):
    """GET /{id}/comments da victim -> 403."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.get(f"/api/invoices/{inv['id']}/comments", headers=attacker)
    assert r.status_code == 403


def test_attacker_cannot_comment_on_victims_invoice(client):
    """POST /{id}/comments da victim -> 403."""
    ctx, att_email, att_pw = _setup_two_departments()
    victim_email, victim_pw, _ = ctx["employee"]

    victim = login(client, victim_email, victim_pw)
    attacker = login(client, att_email, att_pw)

    inv = create_invoice(client, victim)
    r = client.post(
        f"/api/invoices/{inv['id']}/comments",
        headers=attacker,
        json={"body": "malicious comment from attacker"},
    )
    assert r.status_code == 403


def test_uuid_inexistente_returns_404_not_500(client):
    """UUID inexistente NAO deve dar 500."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)
    r = client.get(
        "/api/invoices/00000000-0000-0000-0000-000000000000",
        headers=headers,
    )
    assert r.status_code in (403, 404)  # antes de checar, o role guard pode devolver 403; nao 500
