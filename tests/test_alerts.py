"""Cobertura dos endpoints de alertas — inclui DB-05 (summary vs full)."""
from __future__ import annotations

from tests._helpers import (
    create_full_department_users, create_invoice, login,
)


def test_alerts_summary_returns_counts_only(client):
    """/alerts/summary retorna so numeros — nao materializa listas."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)
    r = client.get("/alerts/summary", headers=emp)
    assert r.status_code == 200
    data = r.json()
    for k in ("overdue_count", "due_72h_count", "old_emission_count",
              "rejected_count", "pending_review_count", "total_alerts"):
        assert k in data
        assert isinstance(data[k], int)
    # NAO deve ter chaves de listagem
    assert "overdue" not in data
    assert "summary" not in data


def test_alerts_full_still_returns_lists(client):
    """/alerts/ preserva formato antigo com listas + summary."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)
    r = client.get("/alerts/", headers=emp)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("overdue"), list)
    assert isinstance(data.get("summary"), dict)


def test_alerts_summary_requires_auth(client):
    """Sem autenticacao -> 401."""
    r = client.get("/alerts/summary")
    assert r.status_code == 401
