"""Facade do router de /api/invoices pos-split (jun/2026, Fase 2).

Antes: 944 linhas com CRUD + FSM + anexos + comentarios + lookup misturados.
Apos split (6 sub-modulos):

  - invoices_helpers.py      — helpers compartilhados (validation_to_422,
                                client_ip, invoice_response, compute_alerts,
                                check_pdf_safety, read_pdf_uploads, models
                                ManagerReviewAction/TransferDirectorRequest/
                                CommentRequest)
  - invoices_lookup.py       — /directors + /lookup-cnpj/{cnpj} (rotas
                                ESTATICAS — devem vir antes de /{invoice_id})
  - invoices_fsm.py          — /{id}/submit, /cancel, /review, /director-review,
                                /transfer-director, /mark-paid (transicoes FSM)
  - invoices_attachments.py  — GET /{id}/attachment (merged), GET/DELETE de
                                /{id}/attachments/{att_id}
  - invoices_comments.py     — GET/POST /{id}/comments
  - invoices_crud.py         — POST /, GET /, GET/PATCH/DELETE /{id}

ORDEM DOS include_router IMPORTA: lookup_router (/directors estatico)
DEVE vir antes de crud_router (que tem /{invoice_id} parametrico),
senao FastAPI captura "directors" como invoice_id.

main.py importa exatamente como antes:
    app.include_router(invoices.router, prefix="/api/invoices", tags=...)
"""
from fastapi import APIRouter

from app.routers import (
    invoices_attachments,
    invoices_comments,
    invoices_crud,
    invoices_fsm,
    invoices_lookup,
)


router = APIRouter()
# Lookup PRIMEIRO — rotas estaticas (/directors, /lookup-cnpj/{cnpj})
router.include_router(invoices_lookup.router)
# Suffix-specific
router.include_router(invoices_fsm.router)
router.include_router(invoices_attachments.router)
router.include_router(invoices_comments.router)
# CRUD por ultimo — tem /{invoice_id} bare
router.include_router(invoices_crud.router)
