# Frontend — estrutura, padrões e como contribuir

Este documento explica a arquitetura do frontend: como os templates,
CSS e JavaScript estão organizados, e por que algumas decisões
foram tomadas.

## Stack

- **Templates**: Jinja2 (renderizado pelo FastAPI no servidor)
- **CSS**: vanilla, organizado em partials com `@import`
- **JavaScript**: vanilla ES2020+, sem build, sem framework, sem npm
- **Renderização**: server-side rendering com hidratação por JavaScript
  (templates HTML completos + JavaScript que adiciona interatividade)

A escolha por "sem build" é deliberada: deploy direto pelo Railway,
sem etapa de bundle, sem `node_modules` em produção, sem cache busting
complicado. Benefício: zero infra de build, qualquer dev edita e funciona.
Custo histórico: a base JavaScript chegou a ser um único `app.js` de
3700+ linhas. Em junho/2026 (P2-1 v3, commit `822bf3d`) foi quebrada
em 14 módulos pequenos sem perder a propriedade "sem build" — ver
seção [Módulos JS](#módulos-js) abaixo.

---

## Estrutura

```
app/
├── templates/                 # Jinja2 (servidor renderiza)
│   ├── base.html              # layout principal (sidebar, header)
│   ├── login.html
│   ├── change_password.html
│   ├── forgot_password.html
│   ├── reset_password.html
│   ├── 404.html, 403.html
│   ├── dashboard.html
│   ├── verify.html, faq.html, privacy.html
│   ├── startup_error.html     # 503 amigável quando config quebrou
│   ├── admin/
│   │   ├── users.html
│   │   ├── user_form.html
│   │   ├── departments.html
│   │   └── audit_logs.html
│   ├── invoices/              # criar, editar, listar, detail
│   ├── manager/               # fila + detail do gestor
│   ├── director/              # fila + detail do diretor
│   ├── finance/               # fila + detail do financeiro
│   └── contas_a_pagar/        # scanner QR
├── static/
│   ├── css/
│   │   ├── main.css           # aggregator
│   │   ├── base/              # tokens, layout, transitions
│   │   ├── components/        # shared, navigation, forms, etc
│   │   ├── pages/             # invoices, admin, drawer, etc
│   │   ├── utilities.css
│   │   └── responsive.css
│   └── js/                    # vanilla, sem build (P2-1 v3, jun/2026)
│       ├── format.js          # helpers puros: formatDate, escapeHtml, statusBadge…
│       ├── documents.js       # CPF/CNPJ: stripDigits, validate, formatDocument
│       ├── core.js            # Auth, apiFetch, showToast, confirmAction, atalhos
│       ├── shell.js           # initShell, login, logout, configuracoes
│       ├── pdf-viewer.js      # PDF inline + escolha de diretor
│       ├── comments.js        # thread de comentários (detail + drawer)
│       ├── password.js        # change / forgot / reset
│       ├── invoices-list.js   # listagem + filtros + paginação
│       ├── invoice-form.js    # criar/editar nota
│       ├── invoice-detail.js  # página de detalhe
│       ├── alerts.js          # /alerts
│       ├── finance.js         # fila + lançamento financeiro
│       ├── review.js          # aprovação gestor/diretor
│       ├── admin-users.js     # CRUD usuários
│       ├── admin-departments.js
│       ├── admin-audit.js
│       ├── drawer.js          # drawer lateral compartilhado
│       ├── dispatcher.js      # roteador DOMContentLoaded por data-page
│       ├── app.js             # stub (compat com referências antigas)
│       ├── dashboard-v2.js    # dashboard (carregado só em /dashboard)
│       ├── verify.js          # página /verify pública
│       ├── scanner.js         # scanner QR
│       ├── not-found.js       # página 404
│       └── offline.js         # tela offline (PWA)
```

---

## Como uma página é renderizada

O fluxo típico de uma página autenticada (ex: `/invoices`):

```
1. Browser pede GET /invoices
2. FastAPI passa pelo page guard em app/security/page_auth.py
   - Lê cookie HttpOnly refresh_token
   - Valida o JWT do refresh
   - Carrega o usuário do banco
   - Confere is_active e password_changed_at
   - Se OK, segue
3. app/routers/pages.py renderiza invoices/list.html
4. Template usa base.html que tem:
   - <link rel="stylesheet" href="/static/css/main.css?v=HASH">
   - <script> para cada módulo JS na ordem certa (ver base.html)
5. Browser baixa CSS e os 19 módulos JS, executa em sequência
   (cada IIFE expõe globals via window.* + namespace window.Economart.<modulo>)
6. dispatcher.js (último) lê data-page="invoices-list" no <body>
7. Despacha para initShell() + initInvoicesList()
8. Funções fazem fetch para /api/invoices/ e populam a tabela
```

A página HTML inicial **já vem com a estrutura visível**. O JavaScript
só preenche dados dinâmicos. Isso evita o flash de "página em branco"
e melhora a experiência percebida.

---

## Auth helper (closure)

O `Auth` em `app/static/js/core.js` é o ponto único de gerenciamento
de sessão no frontend. Implementado como **closure** (IIFE) para
proteger o token:

```javascript
const Auth = (() => {
  let _accessToken = null;        // memória, zera em reload
  let _refreshPromise = null;     // dedup paralelo

  async function _doRefresh() { ... }

  async function ensureToken() {
    if (_accessToken) return _accessToken;
    if (!_refreshPromise) {
      _refreshPromise = _doRefresh().finally(() => {
        _refreshPromise = null;
      });
    }
    return _refreshPromise;
  }

  return {
    getToken: () => _accessToken,
    setToken: (t) => { _accessToken = t; ... },
    ensureToken,
    hasSessionHint: () => ...,
    getUser, setUser, clear,
  };
})();

window.Auth = Auth;  // exposto para scripts secundários
```

Pontos importantes:

- `_accessToken` é privado da closure. JavaScript fora não consegue
  acessar diretamente. Mesmo `Object.keys(Auth)` não revela
- `ensureToken()` faz dedup: 5 fetches paralelos que precisam de
  token disparam **uma** chamada `/refresh`. Os 4 seguintes
  aguardam a mesma Promise
- `sessionStorage.auth_has_session` é apenas um booleano "estou
  logado nesta aba" — não contém segredo. Serve para o
  cliente decidir se vale chamar `/refresh` antes do primeiro
  fetch falhar com 401
- `window.Auth` exposto permite que `verify.js`, `not-found.js`,
  `scanner.js` consumam o mesmo helper sem duplicar lógica

---

## apiFetch (wrapper do fetch)

`apiFetch` em `core.js` é o wrapper que todos os fetches autenticados
devem usar. Responsabilidades:

1. **Anexa Authorization automaticamente** com o token em memória
2. **Pre-hidrata o token** se não tem (chama `ensureToken()`
   antes do fetch). Cobre F5/reload onde memória zerou
3. **Retry automático em 401**: se o servidor responde 401, chama
   `ensureToken()` e tenta de novo com novo token. Só redireciona
   pro /login se a segunda tentativa também falhar
4. **Intercepta 428**: redirect automático pra `/change-password`
   quando o backend exige troca de senha
5. **Intercepta 409 com payload estruturado** (duplicate detection):
   anexa `err.code` e `err.data` no Error para quem chamou tratar
6. **Mensagens amigáveis em 5xx**: stacktrace vai pro console,
   usuário vê "Erro no servidor, tente novamente"
7. **Mensagens de validação Pydantic**: extrai a primeira mensagem
   do array `detail`

Exemplo de uso:

```javascript
try {
  const invoices = await apiFetch('/api/invoices/?status=APROVADO');
  renderTable(invoices.items);
} catch (e) {
  showToast(e.message, 'error');
}
```

Para POST com body:

```javascript
await apiFetch('/api/invoices/123/comments', {
  method: 'POST',
  body: JSON.stringify({ body: 'comentário' }),
});
```

---

## Padrões de UI

### Toast

```javascript
showToast('Nota enviada para o gestor.', 'success');
showToast('Erro ao salvar.', 'error');
```

Toasts somem após 4s. Empilham se vários disparam em sequência.

### Loading overlay

```javascript
showLoading();
try {
  await operacaoLonga();
} finally {
  hideLoading();
}
```

Cobre a tela toda com spinner. Usar para operações que **bloqueiam**
o uso (geração de PDF, upload grande). Para fetch comum, prefira
desabilitar o botão durante a chamada.

### Confirm dialog

```javascript
if (!(await confirmAction('Cancelar esta nota?'))) return;
```

Substituiu `window.confirm` para coerência visual e suporte a
multiline.

### Status badge

```javascript
el.innerHTML = statusBadge(invoice.status);
```

Gera o chip colorido padronizado.

### Format helpers

- `formatDate('2026-06-03')` → `03/06/2026`
- `formatDateTime(isoString)` → `03/06/2026 20:30`
- `formatCurrency(1234.56)` → `R$ 1.234,56`
- `escapeHtml(value)` → escapa `<`, `>`, `&`, `"`, `'`
- `todayInBR()`, `hourInBR()` — para lógica de fuso horário

Sempre que injetar valor de usuário no DOM via `innerHTML`, passar
por `escapeHtml` primeiro.

---

## Drawer (slide-in lateral)

Componente reusável de detalhe lateral usado em várias telas.
Aberto via:

```html
<button data-drawer="uuid-da-nota">Ver</button>
```

Handler global em `dispatcher.js` captura clicks com `data-drawer`
e chama `openInvoiceDrawer(id)` (definido em `drawer.js`). Carrega
a nota, renderiza header + timeline + anexos + comentários + ações
apropriadas para o role do usuário.

Drawer mobile (< 768px) entra como overlay full-screen com
swipe to dismiss.

---

## PDF viewer interno

`pdf-viewer.js` (módulo dedicado) usa o iframe nativo do browser
com `fetchAndOpenPdf` + `loadPdfInline` para renderizar PDFs
inline na página de detail. Suporta:

- Zoom +/- (via CSS transform no iframe)
- Tela cheia (`fullscreen` class no panel)
- Rotação fica a cargo do viewer nativo do browser
  (tentamos rotação CSS própria — quebrava o aspect ratio do iframe
  e o PDF saía do container; ver comentário em `pdf-viewer.js`)

---

## Atalhos de teclado globais

Documentados via `_shortcutsCheatsheet()` (mostrado com `?`).

Principais:

- `/` ou `Ctrl+K`: foca na busca
- `Esc`: fecha drawer / modal
- `?`: abre folha de atalhos
- `g d`: vai pra Dashboard
- `g i`: vai pra Invoices
- `g a`: vai pra Alertas

Implementado em `_wireGlobalShortcuts()` dentro de `core.js`.
Detecta se o usuário está digitando em input antes de capturar.

---

## Responsividade mobile

Estratégia: **mobile first** com breakpoints em `responsive.css`.

- Sidebar vira hamburger menu em < 1024px
- Drawer vira overlay full-screen em < 768px
- Tabelas viram cards empilhados em < 640px
- Inputs ficam maiores (44px altura mínima para toque)

`_wireSidebarMobile()` em `core.js` cuida da lógica do drawer da
sidebar (touch events, backdrop, focus trap).

---

## View Transitions API

Quando o browser suporta (Chrome 126+, fallback noop em outros), o
sistema usa View Transitions para suavizar troca entre páginas.

Combinado com **critical CSS inline** no `<head>` de cada template,
elimina o flash branco entre navegações. UX percebida fica próxima
de SPA sem precisar do custo de manter SPA.

---

## CSS

`main.css` é um aggregator com `@import` ordenado:

```css
@import url("./base/transitions.css");
@import url("./base/tokens.css");
@import url("./base/layout.css");
@import url("./components/shared.css");
@import url("./responsive.css");
@import url("./pages/invoices-review.css");
... etc
```

**Ordem da cascata**:

1. `base/` — variáveis CSS, reset, layout root
2. `components/` — botões, formulários, badges (reusados)
3. `pages/` — específicos por tela
4. `utilities.css` — classes utilitárias (.hidden, .text-muted, etc)
5. `responsive.css` — overrides mobile

**Variáveis CSS** principais em `base/tokens.css`:

```css
:root {
  --color-primary: #FF6B00;        /* laranja Economart */
  --color-primary-dark: #E55A00;
  --color-text: #1f2937;
  --color-text-muted: #6b7280;
  --color-bg: #f4f5f7;
  --color-card: #ffffff;
  --color-border: #e5e7eb;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --shadow-sm: 0 1px 2px rgba(0,0,0,0.05);
  --shadow-md: 0 2px 8px rgba(0,0,0,0.05);
  --font-base: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
```

Para mudar paleta ou raio dos cantos, alterar aqui propaga em todo o site.

---

## Acessibilidade (a11y)

Princípios aplicados:

- **Estrutura semântica**: `<main>`, `<nav>`, `<aside>`, `<header>`
  em vez de divs genéricas
- **Botão-ícone com aria-label**: todo botão que mostra só ícone
  tem `aria-label="descrição"`
- **Tabelas com caption + scope**: leitor de tela navega
  corretamente
- **Form com aria-describedby**: help text ligado ao input por id
- **Focus visible consistente**: `:focus-visible` em botões, links,
  inputs
- **Cor + texto/sigla**: papel não é distinguido só por cor
  (cobre daltônicos)
- **Skip links**: "Pular para conteúdo" oculto, aparece no Tab

Para validar, rodar Lighthouse no Chrome ou axe DevTools. Score
atual: ~90 em a11y.

---

## Como contribuir

### Adicionar uma página nova

1. Criar template em `app/templates/minha-pagina.html` herdando de
   `base.html`
2. Adicionar rota em `app/routers/pages.py` com page guard
3. No bloco `{% block page_id %}minha-pagina{% endblock %}`
   (vira `data-page="minha-pagina"` no `<body>` via base.html)
4. Criar módulo JS em `app/static/js/minha-pagina.js` no padrão IIFE:

```javascript
(function () {
  'use strict';
  window.Economart = window.Economart || {};

  async function initMinhaPagina() {
    const data = await apiFetch('/api/...');
    // popula DOM
  }

  window.Economart.minhaPagina = { initMinhaPagina };
  window.initMinhaPagina = initMinhaPagina;
})();
```

5. Adicionar `<script src="/static/js/minha-pagina.js?v=...">` em
   `base.html` (antes de `dispatcher.js`)
6. Em `dispatcher.js` adicionar branch no DOMContentLoaded:

```javascript
} else if (page === 'minha-pagina') {
  initShell().then(() => initMinhaPagina());
}
```

Se a página NÃO precisa de init próprio (ex: estática como /faq),
basta `data-page` único e o fallback `else if (document.querySelector('.layout'))`
já chama `initShell()` automaticamente.

### Adicionar um endpoint que o frontend consome

1. Adicionar rota no router apropriado em `app/routers/`
2. Definir schemas Pydantic em `app/schemas/`
3. Frontend chama via `apiFetch('/api/...')`

### Adicionar um botão de ação

1. HTML com `data-action="nome"`
2. JavaScript captura via delegação:

```javascript
container.querySelectorAll('button[data-action]').forEach((btn) => {
  btn.addEventListener('click', async () => {
    try {
      if (btn.dataset.action === 'nome') {
        // ação
      }
    } catch (e) { showToast(e.message, 'error'); }
  });
});
```

### Mudar paleta de cores

Editar `app/static/css/base/tokens.css`. Variáveis propagam.

---

## Módulos JS

Estrutura pós-split P2-1 v3 (commit `822bf3d`, jun/2026):

| Módulo | Responsabilidade | Dependências |
|---|---|---|
| `format.js` | Helpers puros: `formatDate`, `formatCurrency`, `escapeHtml`, `statusBadge`, `hourInBR`, `todayInBR` | nenhuma |
| `documents.js` | CPF/CNPJ: `stripDocDigits`, `validateCPF`, `validateCNPJ`, `formatDocument` | nenhuma |
| `core.js` | `Auth`, `apiFetch`, `showToast/Loading`, `confirmAction`, `withButtonLoading`, atalhos globais, sidebar mobile, banner offline, registro do Service Worker, pre-warm `/refresh` | format, documents |
| `shell.js` | `handleLogin`, `logout`, `initShell`, `addApprovalQueueLink`, `initConfiguracoes`, `renderGlobalAvailabilityBanner` | core |
| `pdf-viewer.js` | `fetchAndOpenPdf`, `loadPdfInline`, `renderDirectorList`, `pickDirectorModal`, toolbar | core |
| `comments.js` | Thread de comentários (página de detail + drawer) | core |
| `password.js` | Telas `/change-password`, `/forgot-password`, `/reset-password` | core |
| `invoices-list.js` | Listagem + filtros + paginação | core, format |
| `invoice-form.js` | Criar/editar nota, drop-zone PDF, lookup CNPJ | core, documents, pdf-viewer |
| `invoice-detail.js` | Página de detalhe, ações, timeline | core, pdf-viewer, comments |
| `alerts.js` | Página `/alerts` (5 buckets em accordion) | core |
| `finance.js` | Fila e lançamento financeiro | core, pdf-viewer, invoice-detail, alerts |
| `review.js` | Aprovação gestor/diretor (com modal de reprovação) | core, pdf-viewer, invoice-detail, finance |
| `admin-users.js` | CRUD de usuários + edit quick/full | core |
| `admin-departments.js` | Gestão de setores + vínculo de diretores | core |
| `admin-audit.js` | Visualizador de audit logs paginado | core |
| `drawer.js` | Drawer lateral compartilhado (lista, alertas, fila) | core, pdf-viewer, invoice-detail, comments |
| `dispatcher.js` | `DOMContentLoaded` único; roteia por `data-page` | tudo acima |
| `app.js` | Stub vazio com `window.Economart = {}` (compat com bookmark/cache antigo) | — |

**Padrão de cada módulo**:

```js
(function () {
  'use strict';
  window.Economart = window.Economart || {};

  function minhaFuncao() { /* ... */ }

  // Namespace canônico
  window.Economart.<nome>.minhaFuncao = minhaFuncao;
  // Alias global (compat com callers em outros módulos)
  window.minhaFuncao = minhaFuncao;
})();
```

**Ordem de carregamento** em `base.html`: format → documents → core →
shell → pdf-viewer → comments → password → invoices-list → invoice-form
→ invoice-detail → alerts → finance → review → admin-users →
admin-departments → admin-audit → drawer → app → **dispatcher** (último).

**CSP `script-src 'self'`**: zero `onclick=` ou `<script>` inline em
qualquer template. Toda interação é via `addEventListener` no JS externo.

Plano completo do split + estratégia de rollback em
[plan-appjs-split-v3.md](plan-appjs-split-v3.md).

---

## Pontos de atenção (débito técnico conhecido)

- `@import` em CSS cria download em cascata. Em redes 3G/mobile
  pode adicionar 100-300ms de TTFB. Plano: trocar por múltiplos
  `<link>` direto se Lighthouse mostrar regressão de LCP
- Sem cache busting por content hash determinístico. Hoje busta
  por URL `?v={{ STATIC_VERSION }}` (hash mtime+size dos estáticos).
  Funciona bem em deploy; com worker pool grande do gunicorn pode
  haver janela ms onde versões coexistem. Plano: pipeline de build
  se virar problema
