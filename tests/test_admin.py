"""Admin CRUD — users + departments + defesas contra insider."""
from __future__ import annotations

from tests._helpers import login, make_department, make_user


def test_admin_create_user_success(client):
    """POST /api/admin/users -> 201."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)
    dept_id = make_department()

    r = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "name": "Novo Colaborador",
            "email": "novo@economart.local.example.com",
            "password": "Senha1234!",
            "role": "EMPLOYEE",
            "department_id": dept_id,
            "submit_directly_to_director": True,  # evita precisar de manager_id
        },
    )
    assert r.status_code == 201, r.text
    assert "id" in r.json()


def test_admin_create_duplicate_email_rejected(client):
    """Email ja cadastrado -> 400."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    victim_email, _, _ = make_user(role="EMPLOYEE")
    admin = login(client, admin_email, admin_pw)
    dept_id = make_department()

    r = client.post(
        "/api/admin/users",
        headers=admin,
        json={
            "name": "Dup",
            "email": victim_email,  # ja existe
            "password": "Senha1234!",
            "role": "EMPLOYEE",
            "department_id": dept_id,
            "submit_directly_to_director": True,
        },
    )
    assert r.status_code == 400
    assert "ja cadastrado" in r.json()["detail"].lower()


def test_admin_cannot_reset_other_admin_password(client):
    """ADMIN nao pode redefinir senha de outro ADMIN (anti-sequestro)."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    _, _, other_admin_id = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)

    r = client.post(
        f"/api/admin/users/{other_admin_id}/reset-password",
        headers=admin,
        json={"new_password": "SenhaNova1234!"},
    )
    assert r.status_code == 403
    assert "administrador" in r.json()["detail"].lower()


def test_admin_cannot_deactivate_last_admin(client):
    """PUT desativando o unico ADMIN -> 400."""
    admin_email, admin_pw, admin_id = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)

    # Sem outro admin ativo, nao pode desativar
    r = client.put(
        f"/api/admin/users/{admin_id}",
        headers=admin,
        json={"is_active": False},
    )
    assert r.status_code == 400


def test_admin_cannot_deactivate_self(client):
    """ADMIN nao pode desativar a propria conta."""
    admin_email, admin_pw, admin_id = make_user(role="ADMIN")
    _, _, _ = make_user(role="ADMIN")  # cria outro pra nao ser last
    admin = login(client, admin_email, admin_pw)

    r = client.put(
        f"/api/admin/users/{admin_id}",
        headers=admin,
        json={"is_active": False},
    )
    assert r.status_code == 400
    assert "propria" in r.json()["detail"].lower()


def test_department_crud_flow(client):
    """POST -> GET -> PUT -> DELETE de setor."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)

    # Create
    r = client.post(
        "/api/admin/departments",
        headers=admin,
        json={"name": "TestDeptFlow", "director_ids": []},
    )
    assert r.status_code == 201, r.text
    dept_id = r.json()["id"]

    # List (deve conter o novo)
    r = client.get("/api/admin/departments", headers=admin)
    assert r.status_code == 200
    ids = [d["id"] for d in r.json()]
    assert dept_id in ids

    # Update
    r = client.put(
        f"/api/admin/departments/{dept_id}",
        headers=admin,
        json={"name": "TestDeptFlow-Renomeado", "director_ids": []},
    )
    assert r.status_code == 200

    # Delete
    r = client.delete(f"/api/admin/departments/{dept_id}", headers=admin)
    assert r.status_code == 204


def test_department_cannot_delete_with_members(client):
    """DELETE em setor com membro vinculado -> 400."""
    admin_email, admin_pw, _ = make_user(role="ADMIN")
    admin = login(client, admin_email, admin_pw)

    # Cria dept + user nele
    r = client.post(
        "/api/admin/departments",
        headers=admin,
        json={"name": "DeptComMembro", "director_ids": []},
    )
    dept_id = r.json()["id"]
    make_user(role="EMPLOYEE", department_id=dept_id, submit_directly_to_director=True)

    # DELETE -> 400
    r = client.delete(f"/api/admin/departments/{dept_id}", headers=admin)
    assert r.status_code == 400
