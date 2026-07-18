"""Helpers compartilhados entre os arquivos de teste (jun/2026).

Extraidos pra facilitar novos testes sem duplicar _make_user, _login,
_invoice_payload em cada arquivo.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta


def make_user(
    role: str = "EMPLOYEE",
    manager_id: str | None = None,
    department_id: str | None = None,
    **extra,
) -> tuple[str, str, str]:
    """Cria user direto no DB. Retorna (email, password, id)."""
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
            department_id=department_id,
            must_change_password=False,
        )
        kwargs.update(extra)
        db.add(User(**kwargs))
        db.commit()
    return email, raw_password, uid


def make_department(name: str | None = None) -> str:
    """Cria setor direto no DB. Retorna o id."""
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.models import Department

    dept_id = str(uuid.uuid4())
    dept_name = name or f"Dept-{dept_id[:6]}"
    with Session(engine) as db:
        db.add(Department(id=dept_id, name=dept_name))
        db.commit()
    return dept_id


def login(client, email: str, password: str) -> dict:
    """Cria token JWT direto sem passar por POST /auth/login (evita rate limit
    do middleware que fecha em 5 tentativas/60s e quebra suite de testes).

    Usa create_access_token com sub=user.id + role — mesma factory do endpoint
    real. Retorna headers Authorization prontos.
    """
    from sqlalchemy.orm import Session
    from app.database import engine
    from app.models import User
    from app.security.hashing import verify_password
    from app.security.jwt import create_access_token

    with Session(engine) as db:
        user = db.query(User).filter(User.email == email).first()
        assert user is not None, f"user {email} nao existe"
        assert verify_password(password, user.hashed_password), "senha nao bate"
        token = create_access_token({"sub": user.id, "role": user.role.value})
    return {"Authorization": f"Bearer {token}"}


def login_via_http(client, email: str, password: str) -> tuple[dict, str]:
    """Como login() mas passando pelo endpoint real. Devolve (headers, token).

    Usar so quando o teste precisa exercitar o fluxo de login em si (ex:
    testes de rate limit, timing, etc). Testes comuns devem usar login().
    """
    resp = client.post("/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}, token


def invoice_payload(
    invoice_number: str | None = None,
    supplier_doc: str = "11144477735",
    submit_now: bool = False,
    amount: str = "100.00",
) -> dict:
    """Form-data minimo valido pra criar nota."""
    today = date.today()
    return {
        "invoice_number": invoice_number or f"NF-{uuid.uuid4().hex[:8]}",
        "issue_date": str(today),
        "due_date": str(today + timedelta(days=30)),
        "description": "Servicos de teste para regressao automatica.",
        "amount": amount,
        "supplier_document": supplier_doc,
        "supplier_name": "Fornecedor Teste",
        "submit_now": "true" if submit_now else "false",
    }


def create_invoice(client, headers: dict, payload: dict | None = None) -> dict:
    """Cria nota via POST /api/invoices/ (multipart form). Retorna o JSON."""
    resp = client.post("/api/invoices/", headers=headers, data=payload or invoice_payload())
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def create_full_department_users() -> dict:
    """Cria um setor completo (dept + manager + director + employee) e
    retorna {dept_id, manager: (email, password, id), director: ..., employee: ...}.

    Util pra testes de FSM completo e IDOR — reduz boilerplate.
    """
    dept_id = make_department()
    mgr_email, mgr_pw, mgr_id = make_user(role="MANAGER", department_id=dept_id)
    dir_email, dir_pw, dir_id = make_user(role="DIRECTOR", department_id=dept_id)
    emp_email, emp_pw, emp_id = make_user(
        role="EMPLOYEE", department_id=dept_id, manager_id=mgr_id,
    )
    return {
        "dept_id": dept_id,
        "manager": (mgr_email, mgr_pw, mgr_id),
        "director": (dir_email, dir_pw, dir_id),
        "employee": (emp_email, emp_pw, emp_id),
    }
