"""Facade do pacote invoice_service.

Antes (ate jun/2026): app/services/invoice_service.py monolitico com
1266 linhas misturando notificacoes, queries, FSM, anexos, criacao,
diretores e purge. Apos split (Fase 4 do plan-refactor-master), virou
pacote com 7 sub-modulos:

  - _shared.py    constantes (MAX_*), FSM_TRANSITIONS, _now, _sanitize_text,
                   _safe_currency, _notify_approver, _notify_rejection,
                   _notify_finance_team, _add_history, _add_audit
  - queries.py    _invoice_options(_light), _get_invoice, _can_view,
                   _query_visible_invoices, _status_from_filter,
                   _unaccent_or_lower, get_invoice_or_403, get_invoices_for_user
  - directors.py  _get_director, _get_manager_for_user,
                   _resolve_effective_director, get_available_directors
  - attachments.py _sanitize_attachment_name, _validate_attachment_limits,
                    _add_attachments, _delete_attachment_record,
                    get_attachment, delete_attachment
  - create.py     _check_duplicate_invoice_number,
                   _raise_duplicate_invoice_number, create_invoice,
                   update_invoice
  - fsm.py        _assert_transition, _do_submit, submit_invoice,
                   cancel_invoice, manager_review, director_review,
                   transfer_to_director, mark_paid, delete_invoice
  - purge.py      purge_old_rejected_invoices

Este __init__ re-exporta tudo que era publico antes — chamadas tipo
`from app.services.invoice_service import create_invoice` continuam
funcionando. Tambem expoe os helpers privados (_add_audit, etc.) que
sao usados em invoices.py routers (ADD_COMMENT/VIEW_PDF_MERGED audit).
"""
# Constants
from app.services.invoice_service._shared import (
    FSM_TRANSITIONS,
    MAX_ATTACHMENTS_PER_INVOICE,
    MAX_TOTAL_ATTACHMENT_BYTES,
    REJECTED_AUTO_DELETE_DAYS,
    _add_audit,
    _add_history,
    _notify_approver,
    _notify_finance_team,
    _notify_rejection,
    _now,
    _safe_currency,
    _sanitize_text,
)

# Queries
from app.services.invoice_service.queries import (
    _can_view,
    _get_invoice,
    _invoice_options,
    _invoice_options_light,
    _query_visible_invoices,
    _status_from_filter,
    _unaccent_or_lower,
    get_invoice_or_403,
    get_invoices_for_user,
)

# Directors
from app.services.invoice_service.directors import (
    _get_director,
    _get_manager_for_user,
    _resolve_effective_director,
    get_available_directors,
)

# Attachments
from app.services.invoice_service.attachments import (
    _add_attachments,
    _delete_attachment_record,
    _sanitize_attachment_name,
    _validate_attachment_limits,
    delete_attachment,
    get_attachment,
)

# Create + Update
from app.services.invoice_service.create import (
    _check_duplicate_invoice_number,
    _raise_duplicate_invoice_number,
    create_invoice,
    update_invoice,
)

# FSM (state machine)
from app.services.invoice_service.fsm import (
    _assert_transition,
    _do_submit,
    cancel_invoice,
    delete_invoice,
    director_review,
    manager_review,
    mark_paid,
    submit_invoice,
    transfer_to_director,
)

# Purge
from app.services.invoice_service.purge import purge_old_rejected_invoices


__all__ = [
    # constants
    "FSM_TRANSITIONS", "MAX_ATTACHMENTS_PER_INVOICE", "MAX_TOTAL_ATTACHMENT_BYTES",
    "REJECTED_AUTO_DELETE_DAYS",
    # private helpers usados externamente
    "_add_audit", "_add_history",
    "_notify_approver", "_notify_finance_team", "_notify_rejection",
    "_now", "_safe_currency", "_sanitize_text",
    "_get_invoice", "_can_view", "_query_visible_invoices",
    "_status_from_filter", "_unaccent_or_lower",
    "_invoice_options", "_invoice_options_light",
    "_get_director", "_get_manager_for_user", "_resolve_effective_director",
    "_add_attachments", "_delete_attachment_record",
    "_sanitize_attachment_name", "_validate_attachment_limits",
    "_check_duplicate_invoice_number", "_raise_duplicate_invoice_number",
    "_assert_transition", "_do_submit",
    # public API
    "get_invoice_or_403", "get_invoices_for_user",
    "get_available_directors",
    "get_attachment", "delete_attachment",
    "create_invoice", "update_invoice",
    "cancel_invoice", "delete_invoice", "director_review", "manager_review",
    "mark_paid", "submit_invoice", "transfer_to_director",
    "purge_old_rejected_invoices",
]
