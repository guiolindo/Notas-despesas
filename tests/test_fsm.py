"""FSM da nota fiscal — caminhos felizes + transicoes invalidas.

Cobertura: os 8 estados possiveis + 4 fluxos completos + 5 transicoes
proibidas. Sem estes testes, refactors no invoice_service quebravam
silenciosamente ate alguem clicar na UI.
"""
from __future__ import annotations

import pytest

from tests._helpers import (
    create_full_department_users,
    create_invoice,
    invoice_payload,
    login,
    make_department,
    make_user,
)


# ─── Fluxo feliz completo ────────────────────────────────────────────────────


def test_full_happy_path_employee_manager_director_finance(client):
    """create -> submit -> manager approve -> director approve -> mark_paid."""
    fin_email, fin_pw, _ = make_user(role="FINANCE")
    ctx = create_full_department_users()
    _, _, mgr_id = ctx["manager"]
    dir_email, dir_pw, dir_id = ctx["director"]
    mgr_email, mgr_pw, _ = ctx["manager"]
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    dr = login(client, dir_email, dir_pw)
    fin = login(client, fin_email, fin_pw)

    # 1. Criar rascunho
    inv = create_invoice(client, emp)
    assert inv["status"] == "RASCUNHO"
    inv_id = inv["id"]

    # 2. Employee submit
    r = client.post(f"/api/invoices/{inv_id}/submit", headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "AGUARDANDO_GESTOR"

    # 3. Manager aprova (encaminha ao diretor)
    r = client.post(
        f"/api/invoices/{inv_id}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_id},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "AGUARDANDO_DIRETOR"

    # 4. Director aprova
    r = client.post(
        f"/api/invoices/{inv_id}/director-review",
        headers=dr,
        json={"action": "APPROVE"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "APROVADO"

    # 5. Finance lanca (mark_paid). Endpoint em print_routes.py retorna PDF
    # (nao JSON) — verificamos so status_code e checamos state depois via GET.
    r = client.post(f"/api/invoices/{inv_id}/mark-paid", headers=fin)
    assert r.status_code == 200

    # 6. GET /{id} confirma transicao + history tem as 5 entradas
    r = client.get(f"/api/invoices/{inv_id}", headers=fin)
    data = r.json()
    assert data["status"] == "PAGO"
    history = data["history"]
    actions = [h["action"] for h in history]
    assert "CREATED" in actions
    assert "SUBMITTED" in actions
    assert "APPROVED_MANAGER" in actions
    assert "APPROVED_DIRECTOR" in actions
    assert "MARKED_PAID" in actions


def test_director_self_submit_goes_direct_to_finance(client):
    """Diretor cria propria nota -> vai direto ao Financeiro (auto-aprovada)."""
    ctx = create_full_department_users()
    dir_email, dir_pw, dir_id = ctx["director"]
    dr = login(client, dir_email, dir_pw)

    # Diretor cria com submit_now=True (sem director_id — é ele mesmo)
    payload = invoice_payload(submit_now=True)
    r = client.post("/api/invoices/", headers=dr, data=payload)
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["status"] == "APROVADO"
    # No history: SUBMITTED + APPROVED_DIRECTOR pelo proprio diretor
    actions = [h["action"] for h in data["history"]]
    assert "APPROVED_DIRECTOR" in actions


def test_employee_submit_directly_to_director(client):
    """Employee com submit_directly_to_director=True pula gestor."""
    ctx = create_full_department_users()
    dept_id = ctx["dept_id"]
    _, _, mgr_id = ctx["manager"]
    dir_email, dir_pw, dir_id = ctx["director"]

    emp_email, emp_pw, _ = make_user(
        role="EMPLOYEE",
        department_id=dept_id,
        manager_id=mgr_id,
        submit_directly_to_director=True,
    )
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    r = client.post(
        f"/api/invoices/{inv['id']}/submit?director_id={dir_id}",
        headers=emp,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "AGUARDANDO_DIRETOR"


# ─── Reprovacao ──────────────────────────────────────────────────────────────


def test_manager_reject_forces_edit_before_resubmit(client):
    """Manager reprova -> employee precisa editar descricao antes de resubmit."""
    ctx = create_full_department_users()
    mgr_email, mgr_pw, _ = ctx["manager"]
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    # Manager reprova
    r = client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "REJECT", "comment": "Faltou anexo do boleto original"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "REPROVADO_GESTOR"

    # Resubmit SEM editar descricao -> 400
    r = client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    assert r.status_code == 400
    assert "descricao" in r.json()["detail"].lower() or "descricao" in r.json()["detail"].lower()


def test_director_reject_returns_to_rejected_director(client):
    """Director reprova -> status = REPROVADO_DIRETOR."""
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
    r = client.post(
        f"/api/invoices/{inv['id']}/director-review",
        headers=dr,
        json={"action": "REJECT", "comment": "Valor incompativel com o setor"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "REPROVADO_DIRETOR"


# ─── Cancelamento ────────────────────────────────────────────────────────────


def test_cancel_before_manager_approval_returns_to_draft(client):
    """Cancel antes de qualquer aprovacao -> volta pra RASCUNHO."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    r = client.post(f"/api/invoices/{inv['id']}/cancel", headers=emp)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "RASCUNHO"


def test_cannot_cancel_after_manager_approved(client):
    """Depois que manager aprovou, cancel volta 400."""
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
    r = client.post(f"/api/invoices/{inv['id']}/cancel", headers=emp)
    assert r.status_code == 400


# ─── Transferencia de diretor ────────────────────────────────────────────────


def test_transfer_director_success(client):
    """Diretor A repassa nota pro diretor B — invoice.director_id muda."""
    dept_id = make_department()
    mgr_email, mgr_pw, mgr_id = make_user(role="MANAGER", department_id=dept_id)
    dir_a_email, dir_a_pw, dir_a_id = make_user(role="DIRECTOR", department_id=dept_id)
    dir_b_email, dir_b_pw, dir_b_id = make_user(role="DIRECTOR", department_id=dept_id)
    emp_email, emp_pw, _ = make_user(
        role="EMPLOYEE", department_id=dept_id, manager_id=mgr_id,
    )

    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    dir_a = login(client, dir_a_email, dir_a_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_a_id},
    )

    r = client.post(
        f"/api/invoices/{inv['id']}/transfer-director",
        headers=dir_a,
        json={"new_director_id": dir_b_id, "comment": "Repasse por conflito de interesse conhecido"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["director"]["id"] == dir_b_id


def test_transfer_director_short_comment_rejected(client):
    """Motivo com <10 chars — 400."""
    dept_id = make_department()
    mgr_email, mgr_pw, mgr_id = make_user(role="MANAGER", department_id=dept_id)
    dir_a_email, dir_a_pw, dir_a_id = make_user(role="DIRECTOR", department_id=dept_id)
    _, _, dir_b_id = make_user(role="DIRECTOR", department_id=dept_id)
    emp_email, emp_pw, _ = make_user(
        role="EMPLOYEE", department_id=dept_id, manager_id=mgr_id,
    )
    emp = login(client, emp_email, emp_pw)
    mgr = login(client, mgr_email, mgr_pw)
    dir_a = login(client, dir_a_email, dir_a_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    client.post(
        f"/api/invoices/{inv['id']}/review",
        headers=mgr,
        json={"action": "APPROVE", "director_id": dir_a_id},
    )
    r = client.post(
        f"/api/invoices/{inv['id']}/transfer-director",
        headers=dir_a,
        json={"new_director_id": dir_b_id, "comment": "curto"},
    )
    assert r.status_code == 400


# ─── mark_paid ────────────────────────────────────────────────────────────────


def test_mark_paid_only_after_approved(client):
    """mark_paid antes de APROVADO -> 400."""
    fin_email, fin_pw, _ = make_user(role="FINANCE")
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]

    emp = login(client, emp_email, emp_pw)
    fin = login(client, fin_email, fin_pw)

    # Nota so em rascunho
    inv = create_invoice(client, emp)
    r = client.post(f"/api/invoices/{inv['id']}/mark-paid", headers=fin)
    assert r.status_code == 400


# ─── delete ──────────────────────────────────────────────────────────────────


def test_delete_draft_success(client):
    """DELETE em rascunho — 204."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    r = client.delete(f"/api/invoices/{inv['id']}", headers=emp)
    assert r.status_code == 204


def test_delete_approved_invoice_forbidden(client):
    """DELETE em nota APROVADA -> 400 (obrigacao fiscal)."""
    fin_email, fin_pw, _ = make_user(role="FINANCE")
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
    # Agora status = APROVADO
    r = client.delete(f"/api/invoices/{inv['id']}", headers=emp)
    assert r.status_code == 400


# ─── Transicoes invalidas ────────────────────────────────────────────────────


def test_submit_of_expired_invoice_blocked(client):
    """Nota com due_date < hoje -> submit 400."""
    from datetime import date, timedelta

    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    today = date.today()
    payload = invoice_payload()
    payload["issue_date"] = str(today - timedelta(days=60))
    payload["due_date"] = str(today - timedelta(days=1))  # ontem
    inv = create_invoice(client, emp, payload)

    r = client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    assert r.status_code == 400
    assert "vencimento" in r.json()["detail"].lower()


def test_double_submit_blocked(client):
    """Submit em nota ja em AGUARDANDO_GESTOR -> 400."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    r = client.post(f"/api/invoices/{inv['id']}/submit", headers=emp)
    assert r.status_code == 400
