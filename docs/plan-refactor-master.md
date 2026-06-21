# Plano mestre de refactor — backend + frontend

**Status**: em execução.
**Início**: 2026-06-20.
**Contexto**: sistema em DEV, oportunidade de quebrar agora pra entregar
PROD com arquitetura limpa.

## Diagnóstico inicial

Levantamento de tudo > 300 linhas (após os splits já feitos em jun/2026
do `app.js` 3712 → 14 mód + `admin.py` 1003 → 5 mód + `main.py` 613 → 453).

### Backend Python

| Arquivo | Linhas | Estado | Vai refatorar? |
|---|---|---|---|
| `services/invoice_service.py` | **1266** | 🚨 maior arquivo do projeto, coração do FSM | Fase 4 (alto risco) |
| `routers/invoices.py` | **944** | 🚨 CRUD + FSM + anexos + comentários + lookup | Fase 2 (médio risco) |
| `routers/auth.py` | 594 | médio: login + refresh + password (3 fluxos) | Fase 1 (baixo risco) |
| `main.py` | 453 | melhorou de 613, mas ainda tem health + errors + static | Fase 1 (baixo risco) |
| `routers/admin_users.py` | 449 | criado pelo split admin, mas concentra muito | Fase 5 (opcional) |
| `routers/pending_actions.py` | 382 | aceitável | manter |
| `routers/print_routes.py` | 336 | aceitável | manter |
| `services/email_service.py` | 323 | aceitável | manter |
| `services/pdf_service.py` | 255 | aceitável | manter |
| `services/email_queue_service.py` | 234 | aceitável | manter |
| `routers/pages.py` | 230 | aceitável | manter |

### Frontend JS

| Arquivo | Linhas | Estado | Vai refatorar? |
|---|---|---|---|
| `static/js/core.js` | **645** | grande, mas é foundational (Auth + apiFetch + SW + banner + atalhos) | Fase 3 |
| `static/js/drawer.js` | **446** | drawer com 3 fluxos de review embutidos | Fase 3 |
| `static/js/admin-users.js` | 416 | aceitável | manter |
| `static/js/dashboard-v2.js` | 336 | aceitável | manter |
| `static/js/invoices-list.js` | 271 | aceitável | manter |

### Frontend CSS

| Arquivo | Linhas | Vai refatorar? |
|---|---|---|
| `components/shared.css` | 514 | adiar — é design system unificado, split agora atrapalha mais do que ajuda |
| `pages/drawer-icons-dashboard.css` | 280 | aceitável |
| `pages/admin-content.css` | 250 | aceitável |

### Templates HTML

Grandes mas **conteúdo estático** (texto LGPD, FAQ, etc.). Split agora
quebra mais do que melhora. **Não refatorar**.

| Arquivo | Linhas | Conteúdo |
|---|---|---|
| `privacy.html` | 334 | aviso LGPD completo |
| `faq.html` | 180 | perguntas frequentes |
| `dashboard.html` | 178 | 4 layouts por perfil |

---

## Filosofia das fases

1. **Sistema em DEV**: nenhum cuidado com backward-compat de banco/API
   além do necessário pra não quebrar deploys já em curso (caso o user
   teste em paralelo). Pode rodar `git revert` sem dor.
2. **Cada refactor é UM commit isolado** — rollback granular.
3. **Pytest 21/21 verde** antes e depois.
4. **Smoke runtime contra LAN** depois de cada commit de router/endpoint.
5. **Mecânico, não comportamental**: nenhum endpoint muda assinatura,
   nenhum body muda formato. Só reorganização física.

## Ordem de execução

Cresce em risco. Cada fase só começa quando a anterior está verde.

```
Fase 1 (baixo risco)     → main.py + auth.py
Fase 2 (médio risco)     → invoices.py router (5 sub-arquivos)
Fase 3 (frontend, sem testes) → core.js + drawer.js
Fase 4 (alto risco)      → invoice_service.py (FSM split)
Fase 5 (opcional)        → admin_users.py refinamento
```

---

## Fase 1 — Backend leve

### 1.1 `auth.py` (594 → ~3 arquivos)

**Target**:
- `auth_helpers.py` (~80): `LoginRequest`, `ChangePasswordRequest`,
  `ForgotPasswordRequest`, `ResetPasswordRequest`, `sanitize_email`,
  `_as_utc`, `_LOGIN_TIMING_DUMMY_HASH`, `user_payload`, refresh cookie
  helpers (`_clear_refresh_cookie`, `_clear_refresh_cookie_header`,
  `_refresh_unauthorized`)
- `auth_session.py` (~250): `login`, `refresh`, `logout`, `me`,
  `update_availability`, `_validate_substitute`, `engine_dialect_*`
- `auth_password.py` (~210): `forgot_password`, `reset_password`,
  `change_password`
- `auth.py` (~30): facade que include_router

Helpers ficam num arquivo separado pra não duplicar import — pequeno
mas cresce com features novas.

### 1.2 `main.py` (453 → ~250)

**Target**:
- `app/health.py` (~80): `health`, `health_live`, `health_ready`,
  `health_dependencies`, `_require_admin_or_dev`
- `app/error_handlers.py` (~60): `_is_api_path`, `_not_found_handler`,
  `_http_exception_handler`
- `app/static_views.py` (~30): `service_worker` (`/sw.js`), `offline_page`
- `main.py` (~250): startup_failure, FastAPI(), STATIC_VERSION,
  middlewares, CORS, include_routers

---

## Fase 2 — `routers/invoices.py` (944 → 6 arquivos)

Naturalmente divisível por **resource path**.

**Target** (todos com `APIRouter()` sem prefix; facade inclui):

| Arquivo | Linhas est. | Endpoints |
|---|---|---|
| `invoices_helpers.py` | ~280 | `_validation_to_422`, `_client_ip`, `_client_port`, `_as_utc`, `_compute_invoice_alerts`, `_history_response`, `_prefetch_comment_counts`, `_count_comments`, `invoice_response`, `_can_cancel`, `_check_pdf_safety`, `_read_pdf_upload`, `_read_pdf_uploads`, `MAX_PDF_SIZE` |
| `invoices_crud.py` | ~280 | `create_invoice` (POST /), `list_invoices` (GET /), `get_invoice` (GET /{id}), `update_invoice` (PATCH /{id}), `delete_invoice` (DELETE /{id}) |
| `invoices_fsm.py` | ~150 | `submit_invoice`, `cancel_invoice`, `manager_review`, `director_review`, `transfer_director`, `mark_paid` (do POST /mark-paid local — note: tem outro em print_routes) |
| `invoices_attachments.py` | ~80 | `get_attachment_merged`, `get_attachment_by_id`, `delete_attachment` |
| `invoices_comments.py` | ~120 | `list_comments`, `add_comment` |
| `invoices_lookup.py` | ~50 | `lookup_cnpj_endpoint`, `get_directors` |
| `invoices.py` | ~30 | facade |

**Cuidado especial**: `invoices.py` define `mark_paid` MAS o `print_routes.py`
TAMBÉM define `mark_paid`. São o mesmo endpoint, registrado duas vezes?
Vou checar antes de splitar.

---

## Fase 3 — Frontend grande

### 3.1 `core.js` (645 → 4 arquivos)

**Mantém** o nome `core.js` como facade que carrega:

| Arquivo | Linhas est. | O que tem |
|---|---|---|
| `core-auth.js` | ~140 | IIFE do `Auth` closure + pre-warm `/refresh` + listener click admin-edit |
| `core-api.js` | ~150 | `apiFetch`, `submitInvoiceWithDuplicateCheck`, network event dispatchers |
| `core-ui.js` | ~180 | `showToast`, `showLoading`, `hideLoading`, `withButtonLoading`, `confirmAction`, `toggleSidebar`, `_isMobileViewport`, `_syncSidebarBackdrop`, `_wireSidebarMobile`, listeners globais ESC/backdrop click |
| `core-network.js` | ~150 | `setupNavProgress`, `setupOfflineBanner`, `registerServiceWorker` |
| `core-keyboard.js` | ~120 | `_shortcutsCheatsheet`, `_wireGlobalShortcuts`, `_isTypingInField` |
| `core.js` | ~50 | só os globals foundationals (Economart namespace) — opcional ou stub |

Ordem de carregamento em `base.html`: format → documents → core-auth →
core-api → core-ui → core-network → core-keyboard → shell → resto.

### 3.2 `drawer.js` (446 → 4 arquivos)

| Arquivo | Linhas est. | O que tem |
|---|---|---|
| `drawer-core.js` | ~180 | `_ensureDrawer`, `closeDrawer`, `openInvoiceDrawer`, `_renderDrawerContent`, `_refreshAfterAction`, `_loadDrawerPdf` |
| `drawer-employee.js` | ~120 | `_renderDrawerActions` (employee/criador) |
| `drawer-review.js` | ~150 | `_renderDrawerManagerReview`, `_renderDrawerDirectorReview`, `_wireDrawerReject` |
| `drawer-finance.js` | ~80 | `_renderDrawerFinance` |
| `drawer.js` | ~20 | facade (só pra continuar carregando 1 script — opcional) |

---

## Fase 4 — `services/invoice_service.py` (1266 → 7 arquivos)

**O coração do negócio.** Maior risco. Bem documentado pra reverter
fácil se quebrar.

**Estratégia**: criar um **pacote** `invoice_service/` (não arquivo),
com `__init__.py` re-exportando tudo. Assim os imports atuais
(`from app.services.invoice_service import X`) continuam funcionando.

| Arquivo | Linhas est. | Funções |
|---|---|---|
| `invoice_service/_shared.py` | ~150 | `_now`, `_sanitize_text`, `_safe_currency`, `_notify_approver`, `_notify_rejection`, `_notify_finance_team`, `_add_history`, `_add_audit` |
| `invoice_service/queries.py` | ~180 | `_invoice_options`, `_invoice_options_light`, `_get_invoice`, `_can_view`, `_query_visible_invoices`, `_status_from_filter`, `get_invoice_or_403`, `get_invoices_for_user`, `_unaccent_or_lower` |
| `invoice_service/directors.py` | ~160 | `_get_director`, `_get_manager_for_user`, `_resolve_effective_director`, `get_available_directors` |
| `invoice_service/attachments.py` | ~120 | `_sanitize_attachment_name`, `_validate_attachment_limits`, `_add_attachments`, `_delete_attachment`, `get_attachment`, `delete_attachment` |
| `invoice_service/create.py` | ~250 | `_check_duplicate_invoice_number`, `_raise_duplicate_invoice_number`, `create_invoice`, `update_invoice` |
| `invoice_service/fsm.py` | ~350 | `_assert_transition`, `_do_submit`, `submit_invoice`, `cancel_invoice`, `manager_review`, `director_review`, `transfer_to_director`, `mark_paid`, `delete_invoice` |
| `invoice_service/purge.py` | ~50 | `purge_old_rejected_invoices` |
| `invoice_service/__init__.py` | ~30 | `from .queries import *; from .fsm import *; ...` |

**Validação obrigatória**:
- pytest 21/21 antes e depois
- smoke runtime: criar nota → submit → manager_review → director_review
  → mark_paid (fluxo completo end-to-end)

---

## Fase 5 — Opcional (refinamento `admin_users.py`)

`admin_users.py` ficou em 449 linhas após o split do `admin.py`. O bloco
`update_user` sozinho tem ~150 linhas com regras de validação (janela
24h, last admin guard, snapshot pre-update, etc.). Pode extrair:
- `admin_user_guards.py`: as 8 validações + `_active_admins_except`

Não prioritário. **Avaliar depois** de Fases 1-4.

---

## Validação pós-cada-fase

Antes de cada `git commit`:

```bash
# pytest
python -m pytest tests/ -q                                  # esperado 21/21

# parse de cada novo arquivo Python
python -c "import app.routers.invoices_crud as m; print('OK')"

# smoke runtime (apos rotas)
rm -f test.db
python -c "...seed admin..."
uvicorn app.main:app --port 7145 &
curl localhost:7145/health/live                            # 200
# 1 endpoint de cada router refatorado: 200 ou 4xx (nao 404/500)
```

---

## Rollback strategy

- Cada fase = UM commit (admin foi 8 arquivos em 1 commit, mesmo padrão).
- `git revert <hash>` desfaz totalmente.
- GitHub history preserva tudo. Em DEV não há banco que importa.

---

## Tracking de execução

| Fase | Commit | Status |
|---|---|---|
| 0 — Plano | (este arquivo) | ✅ escrito |
| 1.1 — `auth.py` split | | ⏳ |
| 1.2 — `main.py` extra reduction | | ⏳ |
| 2 — `routers/invoices.py` split | | ⏳ |
| 3.1 — `core.js` split | | ⏳ |
| 3.2 — `drawer.js` split | | ⏳ |
| 4 — `invoice_service.py` split | | ⏳ |
| 5 — `admin_users.py` (opcional) | | ⏳ |

Atualizar tabela após cada commit.
