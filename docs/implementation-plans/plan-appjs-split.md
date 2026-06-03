# Plano Tecnico: Split de `app/static/js/app.js`

## Objetivo

Reduzir risco de regressao no frontend ao dividir `app/static/js/app.js`, hoje com aproximadamente 3100 linhas, em modulos menores por responsabilidade.

Este plano e deliberadamente anterior a qualquer alteracao de codigo porque o arquivo concentra fluxos criticos: autenticacao, listagem de notas, criacao/edicao, detalhe, comentarios, aprovacoes, financeiro, admin, departamentos, forgot/reset password, drawer, atalhos e PDF viewer.

## Estado Atual

Arquivo principal:

- `app/static/js/app.js`

Areas identificadas por leitura estatica:

- Bootstrap/global: `Auth`, `apiFetch`, formatadores, `escapeHtml`, toasts e loading.
- Shell: sidebar, shortcuts, mobile sidebar, logout, `initShell`.
- Auth/configuracoes: login, troca de senha, disponibilidade.
- Invoices list/form/detail: filtros, validacao CPF/CNPJ, upload, viewer, comentarios.
- Review queues: gestor/diretor e modais de aprovacao/reprovacao.
- Financeiro: fila, detalhe, imprimir/lancar.
- Admin: usuarios, auditoria, departamentos.
- Drawer: detalhe lateral e acoes por perfil.
- Password recovery: forgot/reset.

## Riscos

- Dependencias globais implicitas entre funcoes.
- Ordem de carregamento: templates atuais carregam apenas `/static/js/app.js`.
- Estado global compartilhado (`invoiceListState`, `_drawerEl`, `adminAuditState`, `_pdfViewerState`).
- Event listeners baseados em `document.body.dataset.page`.
- CSP atual permite `script-src 'self'`, entao modulos ES podem funcionar, mas precisam ser carregados com `type="module"` ou via bundle.

## Estrategia Recomendada

### Fase 0: Baseline

Antes de qualquer split:

- Rodar `node --check app/static/js/app.js`.
- Capturar lista de `data-page` usados nos templates.
- Criar smoke tests Playwright ou TestClient + browser para paginas principais:
  - `/login`
  - `/dashboard`
  - `/invoices`
  - `/invoices/new`
  - `/admin/users`
  - `/finance/queue`

### Fase 1: Extrair sem mudar loader

Manter `app.js` como ponto unico carregado pelos templates e mover blocos para arquivos que exponham funcoes em `window.Economart`.

Ordem segura:

1. `static/js/core.js`
   - `apiFetch`, `showToast`, `showLoading`, `hideLoading`, formatadores, `escapeHtml`, `confirmAction`.
2. `static/js/auth-shell.js`
   - `Auth`, `initShell`, sidebar, shortcuts, logout.
3. `static/js/invoices.js`
   - list/form/detail/comments/pdf viewer.
4. `static/js/review.js`
   - manager/director queue/detail.
5. `static/js/finance.js`
   - finance queue/detail.
6. `static/js/admin.js`
   - users/audit/departments.
7. `static/js/password.js`
   - forgot/reset/change password.
8. `static/js/bootstrap.js`
   - unico responsavel pelo `DOMContentLoaded` e roteamento por `data-page`.

### Fase 2: Migrar loader

No `base.html`, trocar para:

```html
<script src="/static/js/core.js"></script>
<script src="/static/js/auth-shell.js"></script>
<script src="/static/js/invoices.js"></script>
<script src="/static/js/review.js"></script>
<script src="/static/js/finance.js"></script>
<script src="/static/js/admin.js"></script>
<script src="/static/js/password.js"></script>
<script src="/static/js/bootstrap.js"></script>
```

Isto evita a complexidade inicial de `type="module"` e import maps.

### Fase 3: Opcional ES Modules

Somente depois de estabilizar:

- Converter `core.js` para exports.
- Usar `type="module"` em `bootstrap.js`.
- Remover globais gradualmente.

## Mapa Proposto

| Arquivo | Responsabilidade | Nao deve conter |
|---|---|---|
| `core.js` | utilitarios puros e API fetch | DOM page-specific |
| `auth-shell.js` | sessao, sidebar, shortcuts | regras de nota/admin |
| `invoices.js` | CRUD de notas, comentarios, PDF inline | admin e financeiro |
| `review.js` | filas e acoes gestor/diretor | login/admin |
| `finance.js` | fila financeira e impressao | admin |
| `admin.js` | usuarios, auditoria, departamentos | fluxos de nota comuns |
| `password.js` | forgot/reset/change password | shell/layout |
| `bootstrap.js` | DOMContentLoaded e roteamento | logica de negocio |

## Criterios de Aceite

- Nenhuma tela perde comportamento.
- `node --check` passa em todos os arquivos.
- Nenhum template ganha handler inline.
- Nenhum token/sessao muda durante este split.
- Browser smoke em desktop e mobile passa para as paginas principais.

## Sequencia de Commits

1. Adicionar arquivos novos copiando blocos, sem remover `app.js`.
2. Carregar novos arquivos ainda sem uso, validar CSP e cache.
3. Migrar um dominio por commit, removendo o bloco antigo de `app.js`.
4. Ao final, `app.js` vira bootstrap ou e removido.

## Riscos que Devem Bloquear a Implementacao

- Mudancas simultaneas em auth/refresh token.
- Mudancas simultaneas no fluxo financeiro de print/mark-paid.
- Falta de smoke test manual no navegador apos cada dominio.
