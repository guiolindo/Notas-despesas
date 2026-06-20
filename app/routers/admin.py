"""Facade do router admin pos-split (jun/2026).

O antigo `admin.py` monolitico de 1003 linhas foi dividido em sub-modulos
por subdominio:

  - admin_shared.py        — Pydantic models + helpers compartilhados
  - admin_users.py         — /users, reset-password, unlock, anonymize, managers
  - admin_departments.py   — /departments + listagem de diretores
  - admin_audit.py         — /audit-logs + verify-chain
  - admin_maintenance.py   — /maintenance/purge-rejected

Este arquivo apenas agrega os sub-routers preservando o contrato HTTP:
todas as URLs continuam sob `/api/admin/*`. main.py importa
`from app.routers import admin as admin_router` exatamente como antes.

SMTP foi removido da UI por seguranca (defesa contra admin malicioso).
A configuracao vive em `.env`/painel Railway. Endpoints GET/PUT/POST
em /admin/smtp deixaram de existir.
"""
from fastapi import APIRouter

from app.routers import (
    admin_audit,
    admin_departments,
    admin_maintenance,
    admin_users,
)


router = APIRouter(prefix="/api/admin", tags=["Admin"])
router.include_router(admin_users.router)
router.include_router(admin_departments.router)
router.include_router(admin_audit.router)
router.include_router(admin_maintenance.router)
