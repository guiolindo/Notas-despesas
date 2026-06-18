# Plano de refatoração — split completo do `app.js`

**Status**: em execução.
**Início**: 2026-06-05.
**Versão de partida**: commit `e38f352` — `app.js` com **3712 linhas**.

## Por que estamos fazendo isso

O `app.js` cresceu organicamente porque foi o padrão estabelecido desde
o início do projeto. Cada feature nova ia para o mesmo arquivo. Razões
operacionais que justificaram no curto prazo:

- Acesso fácil a `Auth`, `apiFetch`, `escapeHtml` (closures e funções
  no escopo global).
- Sem framework de módulos (vanilla JS sem build).
- Cada feature pequena não justificava criar um arquivo novo.

**Problemas reais que isso gera agora**:

1. **Risco multiplicado de regressão** — mudar 1 função carrega o
   risco de quebrar features que nem foram tocadas. Já aconteceu
   (commit `2b3c105` foi revertido depois de quebrar botões).
2. **Conflitos de merge** — qualquer dev mexendo no app.js conflita
   com outro dev mexendo no app.js.
3. **Code review** — ler diff no meio de 3712 linhas perde contexto.
4. **Cache** — qualquer mudança invalida 147KB inteiros.
5. **Carga inicial** — usuário baixa o app inteiro mesmo pra usar
   só uma página.
6. **Mental model** — uma feature exige conhecer o arquivo inteiro.

## Histórico de tentativas

| Commit | Resultado |
|---|---|
| `2b3c105` (format.js v1) + `c6e67aa` (password.js v1) | **Revertidos** — regressão "botões mortos" reportada pelo usuário |
| `5873a0d` (P2-1 v2) | **Sucedido** — extraiu `format.js`, `documents.js`, `password.js`, `comments.js` com padrão `window.Economart.<modulo>` + dispatcher central no `app.js`. Sem regressão |

Aprendizados de `5873a0d`:
- Usar namespace `window.Economart.<modulo>.<fn>` em vez de globals soltos.
- Manter dispatcher central em `app.js` (DOMContentLoaded único).
- Auth + apiFetch + pre-warm `/refresh` **NÃO** podem ser movidos sem
  cuidado extremo — são o coração do sistema de sessão.
- Smoke runtime entre cada commit (uvicorn + curl + pytest).
- Validar via `node --check` + `new Function()` antes do push.

## Estado atual (linha por linha)

```
Linhas    Seção                         Funções
─────────────────────────────────────────────────────────────────
1-75      Barra de progresso (IIFE)     setupNavProgress
76-179    Auth helper                   Auth (closure)
180-201   Edit user listener            (anonymous click handler)
202-322   Banner offline + SW           setupOfflineBanner, registerServiceWorker
323-331   Pre-warm /refresh             (IIFE)
332-485   apiFetch + helpers            apiFetch, submitInvoiceWithDuplicateCheck
486-554   UI helpers                    showToast, showLoading, hideLoading,
                                        withButtonLoading, confirmAction
555-630   Sidebar + atalhos             toggleSidebar, _wireSidebarMobile,
                                        _shortcutsCheatsheet, _wireGlobalShortcuts
631-738   Login + auth UI               logout, togglePasswordVisibility,
                                        getSafeNextParam, handleLogin
739-830   Shell + configs               initShell, addApprovalQueueLink,
                                        getInvoiceIdFromPath, invoiceApiPath,
                                        validatePassword, initConfiguracoes,
                                        renderGlobalAvailabilityBanner
831-836   ROLE_LABELS                   (const)
837-1078  Invoices list                 initInvoicesList, loadInvoicesList,
                                        renderInvoicesTable, renderInvoicesSkeleton,
                                        populateDepartmentFilter,
                                        handleInvoiceAction
1079-1351 Invoice form                  setupSupplierDocField, setupInvoiceFileInput,
                                        initInvoiceForm, fillInvoiceForm,
                                        renderExistingAttachmentsList, saveInvoice
1352-1643 Invoice detail                initInvoiceDetail, renderInvoiceAlerts,
                                        renderAttachmentsBlock, renderInvoiceDetail,
                                        renderDetailActions, renderTimeline
1644-1805 PDF helpers                   fetchAndOpenPdf, _printOrMarkPaidEndpoint,
                                        _applyPdfTransform, _setupPdfToolbar,
                                        loadPdfInline
1806-1958 Director selection            renderDirectorList, pickDirectorModal
1959-1991 Alerts                        initAlertsPage, renderAlertTable,
                                        isWithinDateRange
1992-2179 Finance                       loadFinanceInvoices, initFinanceQueue,
                                        renderFinanceQueue, initFinanceDetail,
                                        approvalLine, renderFinanceActions,
                                        daysUntil, daysBadge
2180-2353 Review (manager/director)     reviewInvoice, initReviewQueue,
                                        initReviewDetail
2354-2967 Admin                         adminRoleBadge, adminAvatar,
                                        adminUserStatus, adminLoadManagers,
                                        adminLoadDepartments,
                                        adminToggleManagerField, initAdminUsers,
                                        loadAdminUsers, applyAdminUsersFilter,
                                        renderAdminUsersTable, handleAdminUserAction,
                                        anonymizeAdminUser, openAdminEditModal,
                                        saveAdminEdit, openAdminResetModal,
                                        resetAdminPassword, unlockAdminUser,
                                        toggleAdminUserActive, initAdminUserForm,
                                        loadAdminUserFormData, saveAdminUserForm,
                                        initAdminAuditLogs, loadAdminAuditUsers,
                                        readAdminAuditFilters, loadAdminAuditLogs,
                                        renderAdminAuditLogs, rejectReasonModal
2968-3458 Invoice Drawer                _ensureDrawer, closeDrawer,
                                        openInvoiceDrawer, _renderDrawerContent,
                                        _renderDrawerActions,
                                        _renderDrawerManagerReview,
                                        _renderDrawerDirectorReview,
                                        _renderDrawerFinance, _wireDrawerReject,
                                        _refreshAfterAction, _loadDrawerPdf
3459-3563 Admin Departments             initAdminDepartments + handlers
3564-3589 Listeners globais             (ESC fecha modal, click backdrop fecha)
3590-3711 Dispatcher                    DOMContentLoaded handler
```

## Estrutura alvo

```
app/static/js/
├── core.js              ← Auth + apiFetch + UI helpers + showToast + confirm
├── shortcuts.js         ← atalhos de teclado + sidebar mobile
├── shell.js             ← initShell + availability banner + ROLE_LABELS
├── auth-pages.js        ← handleLogin + logout + getSafeNextParam + validatePassword
├── invoices-list.js     ← lista de notas
├── invoice-form.js      ← criar/editar nota
├── invoice-detail.js    ← detalhe de nota
├── pdf-viewer.js        ← PDF helpers + viewer
├── alerts.js            ← página de alertas
├── finance.js           ← fluxo financeiro
├── review.js            ← fluxo aprovação manager/director
├── admin-users.js       ← admin de usuários (CRUD)
├── admin-departments.js ← admin de setores
├── admin-audit.js       ← visualizador de audit logs
├── drawer.js            ← drawer de invoice (compartilhado)
├── dispatcher.js        ← DOMContentLoaded + roteamento por data-page
└── app.js               ← VAZIO ou minimal (só window.Economart namespace?)

(Já existentes:)
├── format.js            ← format helpers (commit 5873a0d)
├── documents.js         ← CPF/CNPJ helpers (commit 5873a0d)
├── password.js          ← forgot/reset/change handlers (commit 5873a0d)
├── comments.js          ← thread de comentários (commit 5873a0d)
├── offline.js           ← tela offline
├── verify.js            ← página /verify pública
├── scanner.js           ← scanner QR
├── not-found.js         ← página 404
├── dashboard-v2.js      ← dashboard
└── sw.js                ← Service Worker
```

## Padrão de cada módulo novo

```js
/* {nome}.js — {descrição curta}
 *
 * Depende de window.Auth, window.apiFetch, window.{outros helpers}.
 * Carregado DEPOIS de core.js no template (ver base.html).
 * Expoe via namespace window.Economart.{nome}.<fn>.
 * Aliases globais window.<fn> para compat com callers em outros módulos
 * que ainda não migraram.
 */
(function () {
  'use strict';

  window.Economart = window.Economart || {};
  window.Economart.{nome} = window.Economart.{nome} || {};

  // ... funções aqui ...

  // Namespace canônico
  window.Economart.{nome}.fn1 = fn1;
  window.Economart.{nome}.fn2 = fn2;

  // Aliases globais (compat)
  window.fn1 = fn1;
  window.fn2 = fn2;
})();
```

## Ordem de execução

### Fase 1 — Documentação (este arquivo)

- [x] Análise linha-por-linha do app.js
- [x] Mapeamento de funções por seção
- [x] Estrutura alvo definida
- [x] Padrão de módulo definido

### Fase 2 — Extração (commit único)

Ordem importa: cada módulo só pode usar globals **já carregados** antes
dele no template. Ordem dos `<script>` no `base.html`:

```
1. format.js          (helpers puros, sem deps)
2. documents.js       (helpers puros, sem deps)
3. core.js            (Auth, apiFetch, UI helpers, banner offline, SW)
4. shortcuts.js       (depende de window.location e DOM)
5. shell.js           (depende de core)
6. auth-pages.js      (depende de core)
7. pdf-viewer.js      (depende de core)
8. drawer.js          (depende de core + pdf-viewer)
9. comments.js        (depende de core + Auth)
10. password.js       (depende de core + Auth)
11. invoices-list.js  (depende de core + shell)
12. invoice-form.js   (depende de core + documents)
13. invoice-detail.js (depende de core + pdf-viewer + drawer)
14. alerts.js         (depende de core)
15. finance.js        (depende de core + drawer + pdf-viewer)
16. review.js         (depende de core + drawer)
17. admin-users.js    (depende de core)
18. admin-departments.js (depende de core)
19. admin-audit.js    (depende de core)
20. app.js            (vazio ou só namespace setup)
21. dispatcher.js     (DOMContentLoaded, chama window.Economart.<modulo>.init*)
```

### Fase 3 — Validação

Antes de commit:

- [ ] `node --check` em cada arquivo
- [ ] Concatenar e `new Function()` para detectar problemas top-level
- [ ] `pytest tests/ -q` continua 21/21 verde
- [ ] Smoke runtime via uvicorn + curl:
  - `GET /login` → 3 scripts mínimos
  - `GET /forgot-password` → +password.js
  - `GET /dashboard` (sem auth) → vai pra login (esperado)
  - `GET /static/js/<cada arquivo>` → 200 em todos
- [ ] `STATIC_VERSION` atualiza (mtime muda automaticamente)

### Fase 4 — Commit único + push

Mensagem do commit:
```
refactor(js): split completo do app.js em 13+ módulos

3712 linhas → ~13 módulos de 50-300 linhas cada.
[detalhes do que cada módulo cobre]
[smoke validado, pytest 21/21, browser test manual]
```

## Política de rollback

Se o usuário reportar regressão:

1. `git revert <hash do commit>` reverte tudo automaticamente
2. App volta ao estado anterior (`e38f352`) sem perda de dados
3. Re-tentativa fica como follow-up

Sem necessidade de backup local — git history preserva tudo. Sistema
em desenvolvimento, banco em dev SQLite, perda zero.

## Itens conhecidos a manter sem mover

Não mover esses do app.js (ou mover por último com cuidado extremo):

- **Pre-warm `/refresh`** (linhas 323-331): IIFE que dispara antes do
  DOM ficar pronto. Move pra `core.js` mas mantém a posição estrutural
  (ANTES do dispatcher).
- **Auth helper** (linhas 76-179): closure do token em memória.
  Move pra `core.js` mas TESTAR exaustivamente.
- **Listener edit-admin-user** (180-201): pode ficar onde for, mas é
  delegação global de click. Vai pra `core.js`.
- **Service Worker registration** (linhas 220-322): roda no load.
  Move pra `core.js`.

## O que define "sucesso"

- `app.js` vazio (ou com no máximo 50 linhas — só `window.Economart = {}`)
- Cada módulo no diretório `app/static/js/` com nome semântico
- Templates atualizados com os `<script>` corretos
- pytest 21/21 verde
- Smoke runtime OK
- Push único, mensagem detalhada
- Após Ctrl+F5 do usuário, sistema funciona idêntico ao antes
- Próximas mudanças em uma feature mexem em apenas 1 arquivo pequeno

## Tempo estimado

~2-3h de trabalho focado. Vou executar inteiro nesta sessão.

## Quando começar

Imediatamente após salvar este documento.
