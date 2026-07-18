"""Matriz de permissoes: cada role x endpoints sensiveis.

Sem estes testes, um refactor de dependencies.py que quebrasse role
checks passaria despercebido ate um pentest ou um usuario reportar.
"""
from __future__ import annotations

import pytest

from tests._helpers import (
    create_full_department_users,
    create_invoice,
    invoice_payload,
    login,
    make_user,
)


# ─── Endpoints admin (exigem role=ADMIN) ─────────────────────────────────────


@pytest.mark.parametrize("role", ["EMPLOYEE", "MANAGER", "DIRECTOR", "FINANCE", "CONTAS_A_PAGAR"])
def test_non_admin_cannot_list_users(client, role):
    """/api/admin/users so acessivel por ADMIN."""
    email, pw, _ = make_user(role=role)
    headers = login(client, email, pw)
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 403, f"role={role} obteve {r.status_code}"


@pytest.mark.parametrize("role", ["EMPLOYEE", "MANAGER", "DIRECTOR", "FINANCE", "CONTAS_A_PAGAR"])
def test_non_admin_cannot_list_audit_logs(client, role):
    """/api/admin/audit-logs so ADMIN."""
    email, pw, _ = make_user(role=role)
    headers = login(client, email, pw)
    r = client.get("/api/admin/audit-logs", headers=headers)
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["EMPLOYEE", "MANAGER", "DIRECTOR", "FINANCE", "CONTAS_A_PAGAR"])
def test_non_admin_cannot_verify_chain(client, role):
    """/api/admin/audit-logs/verify-chain so ADMIN."""
    email, pw, _ = make_user(role=role)
    headers = login(client, email, pw)
    r = client.get("/api/admin/audit-logs/verify-chain", headers=headers)
    assert r.status_code == 403


def test_admin_can_list_users(client):
    """ADMIN acessa /api/admin/users."""
    email, pw, _ = make_user(role="ADMIN")
    headers = login(client, email, pw)
    r = client.get("/api/admin/users", headers=headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ─── Aprovacoes: so pra quem tem role certa ──────────────────────────────────


def test_employee_cannot_manager_review(client):
    """EMPLOYEE tenta rodar /review — 403 (mesmo sendo o proprio criador)."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    _, _, dir_id = ctx["director"]

    r = client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=emp,
        json={"action": "APPROVE", "director_id": dir_id},
    )
    assert r.status_code == 403


def test_manager_cannot_director_review(client):
    """MANAGER nao pode chamar /director-review."""
    ctx = create_full_department_users()
    mgr_email, mgr_pw, _ = ctx["manager"]
    _, _, dir_id = ctx["director"]
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_id},
    )
    # Manager tenta fazer director-review
    r = client.post(
        f"/api/invoices/{inv['id']}/director-review",
        headers=mgr,
        json={"action": "APPROVE"},
    )
    assert r.status_code == 403


@pytest.mark.parametrize(
    "role",
    ["EMPLOYEE", "MANAGER", "DIRECTOR", "CONTAS_A_PAGAR"],
)
def test_only_finance_can_mark_paid(client, role):
    """mark_paid exige role FINANCE (ou ADMIN via defesa em profundidade)."""
    ctx = create_full_department_users()
    mgr_email, mgr_pw, _ = ctx["manager"]
    dir_email, dir_pw, dir_id = ctx["director"]
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    dr = login(client, dir_email, dir_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_id},
    )
    client.post(
        f"/api/invoices/{inv['id']}/director-review",
        headers=dr,
        json={"action": "APPROVE"},
    )

    # Cria user do role em teste
    intruder_email, intruder_pw, _ = make_user(role=role)
    intruder = login(client, intruder_email, intruder_pw)
    r = client.post(f"/api/invoices/{inv['id']}/mark-paid", headers=intruder)
    assert r.status_code == 403


def test_finance_can_mark_paid(client):
    """FINANCE aprovado -> mark-paid 200."""
    fin_email, fin_pw, _ = make_user(role="FINANCE")
    ctx = create_full_department_users()
    mgr_email, mgr_pw, _ = ctx["manager"]
    dir_email, dir_pw, dir_id = ctx["director"]
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    dr = login(client, dir_email, dir_pw)
    fin = login(client, fin_email, fin_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_id},
    )
    client.post(
        f"/api/invoices/{inv['id']}/director-review",
        headers=dr,
        json={"action": "APPROVE"},
    )
    r = client.post(f"/api/invoices/{inv['id']}/mark-paid", headers=fin)
    # mark-paid retorna PDF binario (endpoint de print_routes); 200 basta
    assert r.status_code == 200


# ─── CONTAS_A_PAGAR read-only ────────────────────────────────────────────────


def test_contas_a_pagar_cannot_create_invoice(client):
    """CONTAS_A_PAGAR nao cria nota."""
    email, pw, _ = make_user(role="CONTAS_A_PAGAR")
    headers = login(client, email, pw)
    r = client.post("/api/invoices/", headers=headers, data=invoice_payload())
    assert r.status_code == 403


def test_finance_cannot_create_invoice(client):
    """FINANCE tambem nao cria nota (so processa aprovadas)."""
    email, pw, _ = make_user(role="FINANCE")
    headers = login(client, email, pw)
    r = client.post("/api/invoices/", headers=headers, data=invoice_payload())
    assert r.status_code == 403


# ─── /auth/me/availability so MANAGER/DIRECTOR ───────────────────────────────


@pytest.mark.parametrize("role", ["EMPLOYEE", "FINANCE", "CONTAS_A_PAGAR", "ADMIN"])
def test_non_approver_cannot_set_availability(client, role):
    """Availability so pra MANAGER e DIRECTOR (ferias)."""
    email, pw, _ = make_user(role=role)
    headers = login(client, email, pw)
    r = client.put(
        "/auth/me/availability",
        headers=headers,
        json={"unavailable": True},
    )
    assert r.status_code == 403
