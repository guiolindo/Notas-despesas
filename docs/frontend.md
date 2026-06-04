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
complicado. Custo: a base JavaScript é grande (um arquivo `app.js`
monolítico). Benefício: zero infra de build, qualquer dev edita
e funciona.

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
│   └── js/
│       ├── app.js             # tudo (3300+ linhas)
│       ├── dashboard-v2.js    # dashboard novo
│       ├── verify.js          # página /verify pública
│       ├── scanner.js         # scanner QR
│       └── not-found.js       # página 404
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
   - <link rel="stylesheet" href="/static/css/main.css">
   - <script src="/static/js/app.js"></script>
5. Browser baixa CSS e JS, executa
6. app.js detecta data-page="invoices-list" no <body>
7. Despacha para initShell() + initInvoicesList()
8. Funções fazem fetch para /api/invoices/ e populam a tabela
```

A página HTML inicial **já vem com a estrutura visível**. O JavaScript
só preenche dados dinâmicos. Isso evita o flash de "página em branco"
e melhora a experiência percebida.

---

## Auth helper (closure)

O `Auth` em `app/static/js/app.js` é o ponto único de gerenciamento
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

`apiFetch` em `app.js` é o wrapper que todos os fetches autenticados
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

Handler global em `app.js` captura clicks com `data-drawer` e
chama `openInvoiceDrawer(id)`. Carrega a nota, renderiza
header + timeline + anexos + comentários + ações apropriadas
para o role do usuário.

Drawer mobile (< 768px) entra como overlay full-screen com
swipe to dismiss.

---

## PDF viewer interno

`pdf-viewer.js` (parte do app.js) usa PDF.js para renderizar PDFs
inline na página de detail. Suporta:

- Zoom +/-
- Rotação 90°
- Tela cheia
- Atalhos de teclado (setas, +/-, R)

Lazy load: PDF.js só é importado quando o usuário abre uma página
de detail. Não pesa a primeira visita.

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

Implementado em `_wireGlobalShortcuts()`. Detecta se o usuário está
digitando em input antes de capturar.

---

## Responsividade mobile

Estratégia: **mobile first** com breakpoints em `responsive.css`.

- Sidebar vira hamburger menu em < 1024px
- Drawer vira overlay full-screen em < 768px
- Tabelas viram cards empilhados em < 640px
- Inputs ficam maiores (44px altura mínima para toque)

`_wireSidebarMobile()` cuida da lógica do drawer da sidebar
(touch events, backdrop, focus trap).

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
3. No `<body>` do template adicionar `data-page="minha-pagina"`
4. No `app.js` adicionar bloco no DOMContentLoaded:

```javascript
} else if (page === 'minha-pagina') {
  initShell().then(() => initMinhaPagina());
}
```

5. Implementar `initMinhaPagina()` que busca dados via `apiFetch`
   e popula DOM

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

## Pontos de atenção (débito técnico conhecido)

- `app/static/js/app.js` tem ~3300 linhas. Tentamos splitar em
  módulos no passado e causou regressão. Plano: refazer com smoke
  test runtime obrigatório antes
- `@import` em CSS cria download em cascata. Em redes 3G/mobile
  pode adicionar 100-300ms de TTFB. Plano: trocar por múltiplos
  `<link>` direto se Lighthouse mostrar regressão de LCP
- Sem cache busting por content hash. Hoje cache busta por
  URL `?v=hash` setada manualmente. Plano: pipeline de build
  quando precisar de mais controle
