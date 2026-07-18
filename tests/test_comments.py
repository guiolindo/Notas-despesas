"""Comentarios na nota — CRUD + validacao + permissoes."""
from __future__ import annotations

from tests._helpers import (
    create_full_department_users,
    create_invoice,
    invoice_payload,
    login,
    make_department,
    make_user,
)


def test_comment_create_success(client):
    """POST /{id}/comments com body valido -> 201."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    r = client.post(
        f"/api/invoices/{inv['id']}/comments",
        headers=emp,
        json={"body": "Comentario de teste - fluxo minimo"},
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["body"] == "Comentario de teste - fluxo minimo"
    assert "id" in data


def test_comment_empty_body_rejected(client):
    """body vazio -> 400."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    r = client.post(
        f"/api/invoices/{inv['id']}/comments",
        headers=emp,
        json={"body": "   "},  # so espacos -> strip vira empty
    )
    assert r.status_code == 400


def test_comment_oversized_rejected(client):
    """body > 2000 chars -> 400."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    r = client.post(
        f"/api/invoices/{inv['id']}/comments",
        headers=emp,
        json={"body": "A" * 3000},
    )
    assert r.status_code == 400


def test_comment_list_paginated(client):
    """GET /{id}/comments retorna items + total + has_next."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    # 3 comentarios
    for i in range(3):
        client.post(
            f"/api/invoices/{inv['id']}/comments",
            headers=emp,
            json={"body": f"Comentario numero {i}"},
        )

    r = client.get(f"/api/invoices/{inv['id']}/comments", headers=emp)
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 3
    assert data["page"] == 1
    assert "items" in data
    assert len(data["items"]) == 3
    assert data["has_next"] is False


def test_comment_pagination_has_next(client):
    """per_page=1 + 3 items -> has_next=True."""
    ctx = create_full_department_users()
    emp_email, emp_pw, _ = ctx["employee"]
    emp = login(client, emp_email, emp_pw)

    inv = create_invoice(client, emp)
    for i in range(3):
        client.post(
            f"/api/invoices/{inv['id']}/comments",
            headers=emp,
            json={"body": f"Comentario paginado {i}"},
        )

    r = client.get(f"/api/invoices/{inv['id']}/comments?per_page=1", headers=emp)
    assert r.status_code == 200
    data = r.json()
    assert data["has_next"] is True
    assert len(data["items"]) == 1
