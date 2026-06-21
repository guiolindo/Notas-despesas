"""Facade do router auth pos-split (jun/2026, Fase 1.1).

Antes: arquivo unico de 594 linhas com login + refresh + logout + me +
availability + forgot + reset + change. Apos split:

  - auth_helpers.py    — Pydantic models + helpers compartilhados
  - auth_session.py    — login, refresh, logout, me, availability
  - auth_password.py   — forgot-password, reset-password, change-password

Este arquivo agrega os sub-routers preservando o contrato HTTP: todas as
URLs continuam sob `/auth/*`. main.py importa exatamente como antes:

    app.include_router(auth.router, prefix="/auth", tags=["Autenticacao"])
"""
from fastapi import APIRouter

from app.routers import auth_password, auth_session


router = APIRouter()
router.include_router(auth_session.router)
router.include_router(auth_password.router)
