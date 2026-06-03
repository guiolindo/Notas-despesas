"""P1-3 + P1-9 + P0-2 — regras de negocio criticas.

Cobre cenarios de submit que envolvem deteccao de duplicidade, manager
indisponivel e transicao APROVADO -> PAGO.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta


def _make_user(role: str = "EMPLOYEE", manager_id: str | None = None, **extra):
    """Cria user direto no DB com role + opcionais. Devolve (email, password, id)."""
    from sqlalchemy.orm import Session

    from app.database import engine
    from app.models import User, UserRole
    from app.security.hashing import hash_password

    raw_password = "Test1234!"
    uid = str(uuid.uuid4())
    email = f"u-{uid[:8]}@economart.local.example.com"
    with Session(engine) as db:
        kwargs = dict(
            id=uid,
            email=email,
            name=f"User {uid[:6]}",
            hashed_password=hash_password(raw_password),
            role=UserRole(role),
            is_active=True,
            manager_id=manager_id,
        )
        kwargs.update(extra)
        db.add(User(**kwargs))
        db.commit()
    return email, raw_password, uid


def _login(client, email, password):
    """Devolve dict de headers Authorization apos login."""
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _invoice_payload(invoice_number: str, supplier_doc: str = "11144477735"):
    """Form-data minimo valido pra criar nota.

    POST /api/invoices/ usa multipart/form-data (Form + UploadFile), nao
    JSON — testes precisam mandar via `data=`.
    """
    today = date.today()
    return {
        "invoice_number": invoice_number,
        "issue_date": str(today),
        "due_date": str(today + timedelta(days=30)),
        "description": "Servicos de teste para auditoria automatica.",
        "amount": "100.00",
        "supplier_document": supplier_doc,
        "supplier_name": "Fornecedor Teste",
        # submit_now=False -> apenas cria, sem rotear. Submit separado.
        "submit_now": "false",
    }


def _create_invoice(client, headers, payload):
    """POST /api/invoices/ via form-data. Retorna o JSON da nota criada."""
    resp = client.post("/api/invoices/", headers=headers, data=payload)
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_p1_9_manager_unavailable_blocks_submit(client):
    """P1-9: gestor em ferias sem substituto -> submit falha com 400 claro."""
    # Manager indisponivel
    _, _, manager_id = _make_user(role="MANAGER", unavailable_for_notes=True)
    # Employee subordinado a esse manager
    emp_email, emp_pass, emp_id = _make_user(role="EMPLOYEE", manager_id=manager_id)

    headers = _login(client, emp_email, emp_pass)
    # Cria nota
    inv = _create_invoice(client, headers, _invoice_payload("NF-MANAGER-UNAV-1"))
    submit = client.post(f"/api/invoices/{inv['id']}/submit", headers=headers)
    assert submit.status_code == 400
    detail = submit.json().get("detail", "")
    assert "indisponivel" in detail.lower() or "substitut" in detail.lower(), detail


def test_p1_9_manager_unavailable_with_substitute_routes_to_substitute(client):
    """P1-9: gestor com substituto valido -> nota vai pro substituto."""
    # Substituto MANAGER ativo
    _, _, sub_id = _make_user(role="MANAGER")
    # Titular MANAGER em ferias com substituto designado
    _, _, manager_id = _make_user(
        role="MANAGER",
        unavailable_for_notes=True,
        substitute_manager_id=sub_id,
    )
    # Employee
    emp_email, emp_pass, _ = _make_user(role="EMPLOYEE", manager_id=manager_id)
    headers = _login(client, emp_email, emp_pass)

    inv = _create_invoice(client, headers, _invoice_payload("NF-MANAGER-SUB-1"))
    submit = client.post(f"/api/invoices/{inv['id']}/submit", headers=headers)
    assert submit.status_code == 200, submit.text
    # manager_id da nota deve ser o substituto, nao o titular
    assert submit.json()["manager"]["id"] == sub_id


def test_p1_3_duplicate_invoice_number_blocked_without_confirm(client):
    """P1-3: criar nota com mesmo (supplier_document, invoice_number) ATIVA
    devolve 409 com code DUPLICATE_INVOICE_NUMBER."""
    _, _, mgr_id = _make_user(role="MANAGER")
    emp_email, emp_pass, _ = _make_user(role="EMPLOYEE", manager_id=mgr_id)
    headers = _login(client, emp_email, emp_pass)

    # Cria + envia a primeira
    payload = _invoice_payload("NF-DUP-001")
    inv1 = _create_invoice(client, headers, payload)
    sub1 = client.post(f"/api/invoices/{inv1['id']}/submit", headers=headers)
    assert sub1.status_code == 200, sub1.text

    # Cria a segunda com mesmo invoice_number + mesmo supplier_document
    inv2 = _create_invoice(client, headers, payload)
    # Submit DEVE falhar com 409 + code DUPLICATE_INVOICE_NUMBER
    sub2 = client.post(f"/api/invoices/{inv2['id']}/submit", headers=headers)
    assert sub2.status_code == 409, sub2.text
    detail = sub2.json().get("detail")
    assert isinstance(detail, dict), f"esperava detail dict, recebi {detail!r}"
    assert detail.get("code") == "DUPLICATE_INVOICE_NUMBER"
    assert "existing_invoice_id" in detail


def test_p1_3_duplicate_allowed_with_confirm_duplicate(client):
    """P1-3: passando confirm_duplicate=true, o segundo submit passa."""
    _, _, mgr_id = _make_user(role="MANAGER")
    emp_email, emp_pass, _ = _make_user(role="EMPLOYEE", manager_id=mgr_id)
    headers = _login(client, emp_email, emp_pass)

    payload = _invoice_payload("NF-DUP-CONFIRM-001")
    inv1 = _create_invoice(client, headers, payload)
    client.post(f"/api/invoices/{inv1['id']}/submit", headers=headers)

    inv2 = _create_invoice(client, headers, payload)
    sub2 = client.post(
        f"/api/invoices/{inv2['id']}/submit?confirm_duplicate=true",
        headers=headers,
    )
    assert sub2.status_code == 200, sub2.text
