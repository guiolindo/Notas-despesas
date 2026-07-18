"""Boundary + validation de campos.

Complementa test_pentest_regression cobrindo Pydantic constraints do
InvoiceCreate/InvoiceUpdate e pagination.
"""
from __future__ import annotations

from tests._helpers import invoice_payload, login, make_user


def test_supplier_document_invalid_cpf_rejected(client):
    """CPF sem digitos validos -> 422."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    payload = invoice_payload()
    payload["supplier_document"] = "00000000000"  # CPF invalido (00000000000)
    r = client.post("/api/invoices/", headers=headers, data=payload)
    assert r.status_code == 422


def test_description_too_short_rejected(client):
    """description com < 10 chars -> 422."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    payload = invoice_payload()
    payload["description"] = "curta"  # 5 chars
    r = client.post("/api/invoices/", headers=headers, data=payload)
    assert r.status_code == 422


def test_due_date_before_issue_date_rejected(client):
    """due_date < issue_date -> 422."""
    from datetime import date, timedelta
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    payload = invoice_payload()
    today = date.today()
    payload["issue_date"] = str(today)
    payload["due_date"] = str(today - timedelta(days=5))
    r = client.post("/api/invoices/", headers=headers, data=payload)
    assert r.status_code == 422


def test_pagination_negative_page_rejected(client):
    """?page=-1 -> 400."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    r = client.get("/api/invoices/?page=-1", headers=headers)
    assert r.status_code == 400


def test_pagination_zero_per_page_rejected(client):
    """?per_page=0 -> 400."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    r = client.get("/api/invoices/?per_page=0", headers=headers)
    assert r.status_code == 400


def test_pagination_huge_per_page_rejected(client):
    """?per_page=999999 -> 400 (max=100)."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    r = client.get("/api/invoices/?per_page=999999", headers=headers)
    assert r.status_code == 400


def test_invalid_date_filter_rejected(client):
    """?from_date=abc -> 400."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    r = client.get("/api/invoices/?from_date=abc", headers=headers)
    assert r.status_code == 400


def test_invalid_status_filter_rejected(client):
    """?status=INEXISTENTE -> 400."""
    email, pw, _ = make_user(role="EMPLOYEE")
    headers = login(client, email, pw)

    r = client.get("/api/invoices/?status=INEXISTENTE", headers=headers)
    assert r.status_code == 400
