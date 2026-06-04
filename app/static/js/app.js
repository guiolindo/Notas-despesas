// ─── Barra de progresso global ─────────────────────────────────────
// Feedback imediato em qualquer navegacao interna: a barra cresce
// rapidamente ate ~70% e completa quando o pageshow dispara na proxima
// pagina. Combina bem com a View Transitions API no Chrome/Edge.
(function setupNavProgress() {
  if (typeof document === 'undefined') return;
  let bar;
  let timer;

  function ensureBar() {
    if (bar) return bar;
    bar = document.getElementById('nav-progress');
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'nav-progress';
      document.body.appendChild(bar);
    }
    return bar;
  }

  function start() {
    const b = ensureBar();
    clearTimeout(timer);
    b.classList.add('active');
    b.style.width = '8%';
    requestAnimationFrame(() => { b.style.width = '70%'; });
  }

  function finish() {
    const b = ensureBar();
    b.style.width = '100%';
    timer = setTimeout(() => {
      b.classList.remove('active');
      setTimeout(() => { b.style.width = '0'; }, 220);
    }, 180);
  }

  function isInternalLink(a, ev) {
    if (!a) return false;
    if (a.target && a.target !== '_self') return false;
    if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey || ev.button !== 0) return false;
    if (a.hasAttribute('download')) return false;
    const href = a.getAttribute('href');
    if (!href || href.startsWith('#') || href.startsWith('javascript:') ||
        href.startsWith('mailto:') || href.startsWith('tel:')) return false;
    try {
      const url = new URL(href, location.href);
      if (url.origin !== location.origin) return false;
      // Mesma URL completa: nao e navegacao real
      if (url.href === location.href) return false;
    } catch (e) { return false; }
    return true;
  }

  document.addEventListener('click', function(ev) {
    const a = ev.target.closest('a[href]');
    if (isInternalLink(a, ev)) start();
  });

  // Submit de formularios que navegam (sem fetch ajax) — show progress
  document.addEventListener('submit', function(ev) {
    const f = ev.target;
    if (!f || f.tagName !== 'FORM') return;
    if (f.dataset.noProgress === '1') return;
    if (f.target && f.target !== '_self') return;
    // Skip se o handler ja chamou preventDefault
    setTimeout(() => { if (!ev.defaultPrevented) start(); }, 0);
  }, true);

  window.addEventListener('pageshow', finish);
  // Fallback: o browser disparou o load
  if (document.readyState === 'complete') finish();
  else window.addEventListener('load', finish);
})();

// ─── Auth helper ───────────────────────────────────────────────────────────
// P1-1 da auditoria: access token sai do localStorage. Antes, XSS bem
// sucedido lia `localStorage.access_token` e assumia a sessao. Agora o
// token vive em memoria (variavel modulo) — um XSS sobreviveria so
// enquanto a aba estiver aberta, e tampouco da pra exfiltrar via DOM
// fora deste contexto.
//
// Reload da pagina (F5) PRECISA continuar funcionando: o cookie
// HttpOnly de refresh ja resolve isso — chamamos /auth/refresh assim
// que o app carrega sem token em memoria. apiFetch detecta 401 e dispara
// _ensureToken() automaticamente.
//
// `user` (objeto basico de identidade pra UI) continua no localStorage —
// nao contem dado sensivel (id, nome, role, dept), serve so pra renderizar
// menus antes do /auth/me chegar. Pode ser sobrescrito a qualquer momento.
const Auth = (() => {
  let _accessToken = null;        // memoria — zera ao recarregar
  let _refreshPromise = null;      // dedup paralelo: 5 fetches concorrentes -> 1 /refresh

  // Reaproveita o sessionStorage SO como sinalizacao "esta logado", pra
  // outras tabs/recarregamentos saberem se vale a pena chamar /refresh
  // antes do primeiro fetch falhar. Nao guardamos token aqui.
  const SESSION_KEY = 'auth_has_session';
  const markSession = () => { try { sessionStorage.setItem(SESSION_KEY, '1'); } catch (e) {} };
  const unmarkSession = () => { try { sessionStorage.removeItem(SESSION_KEY); } catch (e) {} };
  const hasSessionHint = () => {
    try { return sessionStorage.getItem(SESSION_KEY) === '1'; } catch (e) { return false; }
  };

  async function _doRefresh() {
    // Cookie HttpOnly de refresh viaja sozinho. credentials:include necessario
    // pra que o cookie seja enviado mesmo em fetch absoluto.
    const resp = await fetch('/auth/refresh', { method: 'POST', credentials: 'include' });
    if (!resp.ok) {
      _accessToken = null;
      unmarkSession();
      return null;
    }
    const data = await resp.json();
    _accessToken = data.access_token || null;
    if (_accessToken) markSession();
    return _accessToken;
  }

  /** Garante um access token em memoria. Devolve null se refresh falhou. */
  async function ensureToken() {
    if (_accessToken) return _accessToken;
    if (!_refreshPromise) {
      _refreshPromise = _doRefresh().finally(() => { _refreshPromise = null; });
    }
    return _refreshPromise;
  }

  // Migracao defensiva: usuario que estava logado ANTES do P1-1 (token
  // ainda em localStorage) precisa entrar no fluxo novo. Limpa o
  // localStorage.access_token antigo (se existir) e marca o hint pra que
  // o proximo apiFetch hidrate o token via /refresh.
  // Tambem: se ja tem localStorage.user (sessao em curso), marca o hint —
  // F5 sem hint deixa a UI batendo em 401 ate o fallback ressuscitar,
  // causando flicker e suspeita de "botoes nao clicam".
  try {
    const legacyToken = localStorage.getItem('access_token');
    if (legacyToken !== null) {
      localStorage.removeItem('access_token');
      markSession();
    }
    if (localStorage.getItem('user')) {
      markSession();
    }
  } catch (e) { /* storage indisponivel — ignora */ }

  return {
    /** Token cru em memoria. Use ensureToken() pra carregar via /refresh quando vazio. */
    getToken: () => _accessToken,
    setToken: (token) => {
      _accessToken = token || null;
      if (_accessToken) markSession(); else unmarkSession();
    },
    removeToken: () => { _accessToken = null; unmarkSession(); },
    ensureToken,
    /** Hint de sessao (sem o segredo) — usado por boot scripts pra decidir
     *  se vale chamar /refresh antes do primeiro fetch falhar. */
    hasSessionHint,

    getUser: () => {
      try { return JSON.parse(localStorage.getItem('user') || 'null'); } catch (e) { return null; }
    },
    setUser: (user) => {
      try { localStorage.setItem('user', JSON.stringify(user)); } catch (e) {}
      markSession();
    },
    clear: () => {
      _accessToken = null;
      unmarkSession();
      try { localStorage.removeItem('user'); } catch (e) {}
    },
  };
})();

// Exposto pra scripts secundarios (verify.js, scanner.js etc.) consumirem
// o mesmo helper sem duplicar logica e sem mexer em localStorage.
if (typeof window !== 'undefined') {
  window.Auth = Auth;
  // Namespace de modulos. Sub-modulos (password.js, etc.) anexam aqui em
  // vez de poluir o global com nomes soltos. P2-1 (auditoria).
  window.Economart = window.Economart || {};
}

// Pre-aquece /auth/refresh assim que o script carrega — antes do DOM ficar
// pronto. Em redes/instancias com cold start (Railway free tier), o /refresh
// pode demorar 3-8s. Disparando aqui no topo do parsing, ate o
// DOMContentLoaded disparar e o usuario clicar em algo, o token tipicamente
// ja chegou. Sem isso, o primeiro click acionava ensureToken sequencialmente
// e o usuario via delay visivel ("ficou parado uns 10s"). Defesa: silencia
// rejection — se falhar, apiFetch ainda tenta novamente em 401.
try {
  if (Auth.hasSessionHint && Auth.hasSessionHint()) {
    Auth.ensureToken().catch(() => {});
  }
} catch (e) { /* ignora — pior caso cai no fluxo 401 */ }

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  // P1-1: token vive em memoria. Se ainda nao temos (reload, abrir outra
  // aba), tenta hidratar via cookie HttpOnly de refresh antes do fetch.
  //
  // Defesa-em-profundidade: tentamos ensureToken SEMPRE quando nao temos
  // token, sem depender do hint. O hint acelera o feedback (evita um round
  // de 401 -> retry), mas em sessoes antigas (pre-P1-1) ele pode nao
  // existir. O custo extra de chamar /refresh quando ja seriamos anonimos
  // e baixo: cookie HttpOnly ausente -> backend responde rapido com 401
  // e ensureToken devolve null sem efeito colateral.
  let token = Auth.getToken();
  if (!token) {
    token = await Auth.ensureToken();
  }
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response = await fetch(url, { ...options, headers, credentials: 'include' });

  // 401: tenta UMA renovacao via cookie de refresh antes de mandar pro
  // /login. Cobre access expirado naturalmente (1h) sem virar tela branca
  // pro usuario. Se /refresh tambem falhar, ai sim logout.
  if (response.status === 401) {
    const newToken = await Auth.ensureToken();
    if (newToken && newToken !== token) {
      headers.set('Authorization', `Bearer ${newToken}`);
      response = await fetch(url, { ...options, headers, credentials: 'include' });
    }
    if (response.status === 401) {
      Auth.clear();
      window.location.href = '/login';
      throw new Error('Sessao expirada');
    }
  }
  // 428 Precondition Required = backend exige troca de senha antes da acao.
  // P1-8 da auditoria: a regra deixou de ser apenas redirect do frontend.
  // Manda o usuario pra change-password se ele tentar bater em endpoint
  // bloqueado (ex: integrator direto, ou usuario que abriu outra aba).
  if (response.status === 428) {
    if (window.location.pathname !== '/change-password') {
      window.location.href = '/change-password';
    }
    throw new Error('Troca de senha obrigatoria antes de continuar.');
  }

  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    // Erros 5xx vem com detail tecnico/stacktrace ou HTML. Mostra mensagem
    // amigavel pro usuario; o detalhe vai pro console pra debug.
    if (response.status >= 500) {
      console.error('[apiFetch] 5xx:', response.status, data);
      throw new Error('Erro no servidor. Tente novamente em alguns segundos.');
    }
    // Erros de validacao do Pydantic vem como array [{loc, msg, type}]
    if (Array.isArray(data?.detail)) {
      const first = data.detail[0];
      const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : '';
      throw new Error(field ? `${field}: ${first.msg}` : (first?.msg || 'Dados invalidos'));
    }
    // 409 com payload estruturado (ex: DUPLICATE_INVOICE_NUMBER do P1-3).
    // Repassa o objeto inteiro num campo .data pra quem chama poder oferecer
    // 'enviar mesmo assim' sem reparsear a mensagem.
    if (response.status === 409 && data?.detail && typeof data.detail === 'object') {
      const err = new Error(data.detail.message || 'Conflito de duplicidade');
      err.code = data.detail.code;
      err.data = data.detail;
      err.status = 409;
      throw err;
    }
    throw new Error(data?.detail || (typeof data === 'string' ? data : null) || 'Erro na requisicao');
  }
  return data;
}

/** Submete uma nota com tratamento do soft-check de duplicidade (P1-3).
 *  Tenta uma vez; se backend devolver DUPLICATE_INVOICE_NUMBER, pergunta ao
 *  usuario se quer enviar mesmo assim e reenvia com confirm_duplicate=true.
 *  Devolve a Invoice atualizada ou null se o usuario cancelou. */
async function submitInvoiceWithDuplicateCheck(invoiceId, directorId = null) {
  const base = `/api/invoices/${invoiceId}/submit`;
  const query = new URLSearchParams();
  if (directorId) query.set('director_id', directorId);
  try {
    return await apiFetch(`${base}?${query.toString()}`, { method: 'POST' });
  } catch (err) {
    if (err.code !== 'DUPLICATE_INVOICE_NUMBER') throw err;
    const ok = await confirmAction(
      `${err.data?.message || 'Nota duplicada detectada.'}\n\nDeseja enviar mesmo assim?`,
    );
    if (!ok) return null;
    query.set('confirm_duplicate', 'true');
    return apiFetch(`${base}?${query.toString()}`, { method: 'POST' });
  }
}

function showToast(message, type = 'info') {
  const container = document.getElementById('toast-container') || document.body.appendChild(document.createElement('div'));
  container.id = 'toast-container';
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 250);
  }, 4000);
}

function showLoading() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.classList.remove('hidden');
}

function hideLoading() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.classList.add('hidden');
}

// Helpers de formatacao (TZ, formatDate, formatDateTime, hourInBR,
// todayInBR, formatCurrency, escapeHtml, statusBadge) movidos para
// app/static/js/format.js (P2-1 auditoria). Acesso via window.* (alias)
// ou window.Economart.format.*. format.js carrega ANTES de app.js.

function confirmAction(message) {
  return new Promise((resolve) => {
    // Iframes nativos de PDF (Chrome/Edge) renderizam fora do contexto
    // HTML normal e IGNORAM z-index — ficam sempre por cima de qualquer
    // overlay do site. Bug reportado pelo usuario: pop-up de confirmacao
    // de "Imprimir e Lancar" ficava por tras do PDF. Solucao padrao:
    // esconder iframes enquanto o modal estiver aberto, restaurar quando
    // fecha.
    const hiddenFrames = [];
    document.querySelectorAll('iframe').forEach((el) => {
      if (el.style.visibility !== 'hidden') {
        hiddenFrames.push(el);
        el.style.visibility = 'hidden';
      }
    });
    function restoreFrames() {
      hiddenFrames.forEach((el) => { el.style.visibility = ''; });
    }

    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h2>Confirmar acao</h2>
        <p class="text-muted">${message}</p>
        <div class="modal-actions">
          <button class="btn btn-ghost" data-action="cancel">Cancelar</button>
          <button class="btn btn-primary" data-action="confirm">Confirmar</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.addEventListener('click', (event) => {
      const action = event.target.dataset.action;
      if (!action) return;
      backdrop.remove();
      restoreFrames();
      resolve(action === 'confirm');
    });
  });
}

function toggleSidebar() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  sidebar.classList.toggle('collapsed');
  _syncSidebarBackdrop();
}

function _isMobileViewport() {
  return window.matchMedia('(max-width: 768px)').matches;
}

function _syncSidebarBackdrop() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  let backdrop = document.getElementById('sidebar-backdrop');
  const open = sidebar.classList.contains('collapsed') && _isMobileViewport();
  if (open) {
    if (!backdrop) {
      backdrop = document.createElement('div');
      backdrop.id = 'sidebar-backdrop';
      backdrop.className = 'sidebar-backdrop';
      backdrop.addEventListener('click', () => {
        sidebar.classList.remove('collapsed');
        _syncSidebarBackdrop();
      });
      document.body.appendChild(backdrop);
    }
    backdrop.classList.add('active');
  } else if (backdrop) {
    backdrop.classList.remove('active');
  }
}

// ─── Atalhos de teclado globais ─────────────────────────────────────
// /         -> foca primeiro campo de busca da pagina
// n         -> /invoices/new (so quem pode criar nota)
// g d       -> dashboard
// g i       -> /invoices
// g a       -> /alerts
// ?         -> cheatsheet
function _shortcutsCheatsheet() {
  const me = Auth.getUser();
  const canCreate = me && !['CONTAS_A_PAGAR', 'FINANCE'].includes(me.role);
  const rows = [
    ['<kbd>/</kbd>', 'Focar a busca'],
    canCreate ? ['<kbd>n</kbd>', 'Nova nota'] : null,
    ['<kbd>g</kbd> <kbd>d</kbd>', 'Dashboard'],
    ['<kbd>g</kbd> <kbd>i</kbd>', 'Notas fiscais'],
    ['<kbd>g</kbd> <kbd>a</kbd>', 'Alertas'],
    ['<kbd>?</kbd>', 'Mostrar esta lista'],
    ['<kbd>Esc</kbd>', 'Fechar drawer/modal'],
  ].filter(Boolean);
  const html = `<div class="modal-backdrop" id="shortcuts-modal-backdrop">
    <div class="modal">
      <h2 style="font-size:1.1rem;margin-bottom:1rem">Atalhos de teclado</h2>
      <table class="shortcuts-table">
        <caption class="sr-only">Atalhos de teclado disponiveis</caption>
        ${rows.map(([k, l]) => `<tr><td>${k}</td><td>${l}</td></tr>`).join('')}
      </table>
      <p class="text-muted text-xs" style="margin-top:1rem">
        Atalhos sao desativados enquanto voce digita em um campo. Pressione <kbd>Esc</kbd> para fechar.
      </p>
      <div style="text-align:right;margin-top:1rem">
        <button class="btn btn-ghost btn-sm" id="shortcuts-close">Fechar</button>
      </div>
    </div>
  </div>`;
  const tmp = document.createElement('div');
  tmp.innerHTML = html;
  const overlay = tmp.firstChild;
  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  overlay.querySelector('#shortcuts-close').addEventListener('click', close);
  document.body.appendChild(overlay);
}

let _shortcutPrefix = null;       // 'g' apos primeira tecla
let _shortcutPrefixTimer = null;

function _isTypingInField(target) {
  if (!target) return false;
  const tag = target.tagName || '';
  if (target.isContentEditable) return true;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT';
}

function _wireGlobalShortcuts() {
  if (window._shortcutsBound) return;
  window._shortcutsBound = true;
  document.addEventListener('keydown', (e) => {
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    if (_isTypingInField(e.target)) {
      if (e.key === 'Escape' && _shortcutPrefix) _shortcutPrefix = null;
      return;
    }
    // 1a tecla 'g' aguarda 2a tecla
    if (e.key === 'g' && !_shortcutPrefix) {
      _shortcutPrefix = 'g';
      clearTimeout(_shortcutPrefixTimer);
      _shortcutPrefixTimer = setTimeout(() => { _shortcutPrefix = null; }, 1200);
      e.preventDefault();
      return;
    }
    if (_shortcutPrefix === 'g') {
      _shortcutPrefix = null;
      if (e.key === 'd') { window.location.href = '/dashboard'; e.preventDefault(); return; }
      if (e.key === 'i') { window.location.href = '/invoices'; e.preventDefault(); return; }
      if (e.key === 'a') { window.location.href = '/alerts'; e.preventDefault(); return; }
      return;
    }
    if (e.key === '/') {
      const search = document.querySelector('input[type="search"]') || document.querySelector('#invoices-search');
      if (search) { search.focus(); e.preventDefault(); }
      return;
    }
    if (e.key === 'n') {
      const me = Auth.getUser();
      if (me && !['CONTAS_A_PAGAR', 'FINANCE'].includes(me.role)) {
        window.location.href = '/invoices/new';
        e.preventDefault();
      }
      return;
    }
    if (e.key === '?' || (e.shiftKey && e.key === '/')) {
      _shortcutsCheatsheet();
      e.preventDefault();
      return;
    }
    if (e.key === 'Escape') {
      // Fecha drawer global se aberto
      document.querySelector('.drawer.open, .drawer-open')?.classList.remove('open', 'drawer-open');
      // Fecha modal de atalhos
      document.getElementById('shortcuts-modal-backdrop')?.remove();
    }
  });
}

// Em mobile: clicar num link da nav fecha o drawer automaticamente.
// Resize do desktop: garante que o backdrop suma se a janela cresceu.
function _wireSidebarMobile() {
  const sidebar = document.getElementById('sidebar');
  if (!sidebar) return;
  sidebar.querySelectorAll('.nav-item').forEach((link) => {
    link.addEventListener('click', () => {
      if (_isMobileViewport()) {
        sidebar.classList.remove('collapsed');
        _syncSidebarBackdrop();
      }
    });
  });
  window.addEventListener('resize', () => {
    if (!_isMobileViewport()) {
      const backdrop = document.getElementById('sidebar-backdrop');
      if (backdrop) backdrop.classList.remove('active');
    }
  });
}

async function logout() {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } finally {
    Auth.clear();
    window.location.href = '/login';
  }
}

function togglePasswordVisibility() {
  const input = document.getElementById('password');
  if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

// Pega ?next= da URL e retorna so se for um path interno seguro
// (mesmo origin, comeca com /, nao e //). Caso contrario, devolve null
// e o caller usa /dashboard como destino padrao.
function getSafeNextParam() {
  try {
    const raw = new URLSearchParams(window.location.search).get('next');
    if (!raw) return null;
    if (!raw.startsWith('/') || raw.startsWith('//')) return null;
    // Bloqueia loops pra /login e fluxo de troca de senha
    if (raw.startsWith('/login') || raw.startsWith('/change-password')) return null;
    return raw;
  } catch {
    return null;
  }
}

async function handleLogin(event) {
  event.preventDefault();
  const button = document.getElementById('login-btn');
  const errorEl = document.getElementById('login-error');
  errorEl.classList.add('hidden');
  button.disabled = true;
  button.textContent = 'Entrando...';

  try {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      errorEl.textContent = data.detail || 'Erro ao fazer login';
      errorEl.classList.remove('hidden');
      return;
    }
    Auth.setToken(data.access_token);
    Auth.setUser(data.user);
    // Troca de senha sempre vence; senao, respeita ?next=/algum-caminho
    // (ex: usuario abriu /verify/<id> e clicou em 'Entrar para ver completo')
    if (data.user.must_change_password) {
      window.location.href = '/change-password';
    } else {
      const next = getSafeNextParam();
      window.location.href = next || '/dashboard';
    }
  } catch {
    errorEl.textContent = 'Erro de conexao. Tente novamente.';
    errorEl.classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = 'Entrar';
  }
}

const ROLE_LABELS = {
  ADMIN:           'Administrador',
  MANAGER:         'Gestor',
  DIRECTOR:        'Diretor',
  FINANCE:         'Financeiro',
  EMPLOYEE:        'Funcionario',
  CONTAS_A_PAGAR:  'Contas a Pagar',
};

async function initShell() {
  let user = Auth.getUser();
  if (!user) { window.location.href = '/login'; return; }

  // Atualiza dados do usuario a cada pagina (pega must_change_password e submit_directly_to_director frescos)
  try {
    const fresh = await apiFetch('/auth/me');
    user = { ...user, ...fresh };
    Auth.setUser(user);
  } catch {
    // Se falhar (token expirado o apiFetch já redireciona para /login)
  }

  // Redireciona para trocar senha se obrigatorio
  if (user.must_change_password && window.location.pathname !== '/change-password') {
    window.location.href = '/change-password';
    return;
  }

  // Shell ja vem visivel do HTML (cores aplicadas inline no <head>).
  // JS so completa os textos dinamicos do header.
  document.getElementById('header-user-name').textContent = user.name;
  _wireSidebarMobile();
  _wireGlobalShortcuts();
  document.getElementById('header-user-role').textContent = ROLE_LABELS[user.role] || user.role;
  addApprovalQueueLink(user.role);
  renderGlobalAvailabilityBanner();
  try {
    const data = await apiFetch('/alerts/');
    const count = data.summary.total_alerts;
    if (count > 0) {
      const el = document.getElementById('alert-count');
      el.textContent = count;
      el.classList.remove('hidden');
    }
  } catch {}
}

function addApprovalQueueLink(role) {
  const nav = document.querySelector('.sidebar-nav');
  if (!nav) return;
  if (role === 'ADMIN' && !document.getElementById('nav-admin-users')) {
    document.getElementById('nav-admin')?.remove();
    const users = document.createElement('a');
    users.href = '/admin/users';
    users.id = 'nav-admin-users';
    users.className = 'nav-item';
    users.innerHTML = '<span class="nav-icon">&#9786;</span> Usuarios';
    const depts = document.createElement('a');
    depts.href = '/admin/departments';
    depts.id = 'nav-admin-depts';
    depts.className = 'nav-item';
    depts.innerHTML = '<span class="nav-icon">&#9670;</span> Setores';
    const audit = document.createElement('a');
    audit.href = '/admin/audit-logs';
    audit.id = 'nav-admin-audit';
    audit.className = 'nav-item';
    audit.innerHTML = '<span class="nav-icon">&#9998;</span> Auditoria';
    // 'Email automatico' removido — SMTP agora e configurado via .env
    // (so quem opera o Railway, nao quem tem login no app).
    nav.insertBefore(users, document.getElementById('nav-alerts'));
    nav.insertBefore(depts, document.getElementById('nav-alerts'));
    nav.insertBefore(audit, document.getElementById('nav-alerts'));
  }
  if (['MANAGER', 'DIRECTOR'].includes(role) && !document.getElementById('nav-approval-queue')) {
    const href = role === 'MANAGER' ? '/manager/queue' : '/director/queue';
    const item = document.createElement('a');
    item.href = href;
    item.id = 'nav-approval-queue';
    item.className = 'nav-item';
    item.innerHTML = '<span class="nav-icon">&#8801;</span> Fila de Aprovacao <span class="badge-count hidden" id="queue-count-nav"></span>';
    nav.insertBefore(item, document.getElementById('nav-alerts'));
  }
  if (role === 'FINANCE' && !document.getElementById('nav-finance-queue')) {
    const queue = document.createElement('a');
    queue.href = '/finance/queue';
    queue.id = 'nav-finance-queue';
    queue.className = 'nav-item';
    queue.innerHTML = '<span class="nav-icon">&#9724;</span> Lancamentos <span class="badge-count hidden" id="finance-count-nav"></span>';
    nav.insertBefore(queue, document.getElementById('nav-alerts'));
    // Historico foi fundido na pagina /invoices (que ja tem totalizer + filtros completos)
  }
  if (role === 'CONTAS_A_PAGAR' && !document.getElementById('nav-scanner')) {
    // Scanner: bipador / camera (Fase 4)
    const scan = document.createElement('a');
    scan.href = '/contas-a-pagar/scanner';
    scan.id = 'nav-scanner';
    scan.className = 'nav-item';
    scan.innerHTML = '<span class="nav-icon">&#9783;</span> Scanner QR';
    nav.insertBefore(scan, document.getElementById('nav-alerts'));
    // Esconde acao 'Nova nota' (read-only)
    document.getElementById('nav-new-invoice')?.remove();
  }
}

// Dashboard agora e renderizado por dashboard.html + dashboard-v2.js.
// initDashboard/renderStats/renderAlerts/renderRecentInvoices antigos
// foram removidos — apontavam pra elementos (#stats-grid, #alerts-section,
// #recent-invoices) que nao existem mais no template novo.

function getInvoiceIdFromPath() {
  const match = window.location.pathname.match(/\/invoices\/([^/]+)/);
  return match ? match[1] : null;
}

function invoiceApiPath(invoiceId = '') {
  return invoiceId ? `/api/invoices/${invoiceId}` : '/api/invoices/';
}

function validatePassword(password) {
  return password.length >= 8 && /[A-Za-z]/.test(password) && /\d/.test(password);
}

// Exposicao explicita dos helpers globais que app.js DEFINE e sub-modulos
// (password.js, etc.) CONSOMEM. Helpers que sub-modulos definem
// (formatDate, escapeHtml, validateCPF, etc.) ficam expostos pelos
// respectivos arquivos (format.js, documents.js). P2-1 (auditoria).
if (typeof window !== 'undefined') {
  window.apiFetch = apiFetch;
  window.showToast = showToast;
  window.confirmAction = confirmAction;
  window.validatePassword = validatePassword;
}

async function initConfiguracoes() {
  const user = Auth.getUser();
  if (!user) return;
  const card = document.getElementById('config-availability-card');
  // So MANAGER e DIRECTOR podem pausar recebimento
  if (!['MANAGER', 'DIRECTOR'].includes(user.role)) {
    return;
  }
  card.classList.remove('hidden');

  const me = await apiFetch('/auth/me');
  const toggle = document.getElementById('config-unavailable-toggle');
  toggle.checked = Boolean(me.unavailable_for_notes);
  document.getElementById('config-availability-status')
    .classList.toggle('hidden', !me.unavailable_for_notes);

  // Substituto — so pra DIRECTOR
  const subSection = document.getElementById('config-substitute-section');
  const subSel = document.getElementById('config-substitute-select');
  if (user.role === 'DIRECTOR' && subSection && subSel) {
    subSection.classList.remove('hidden');
    try {
      const allDirectors = await apiFetch('/api/invoices/directors');
      allDirectors
        .filter((d) => d.id !== user.id && d.is_active && !d.unavailable_for_notes)
        .forEach((d) => {
          const opt = document.createElement('option');
          opt.value = d.id;
          opt.textContent = d.name + (d.department_name ? ` · ${d.department_name}` : '');
          if (d.id === me.substitute_director_id) opt.selected = true;
          subSel.appendChild(opt);
        });
    } catch {
      subSection.classList.add('hidden');
    }
  }

  async function applyChange() {
    const payload = {
      unavailable: toggle.checked,
      substitute_director_id: subSel ? (subSel.value || null) : null,
    };
    try {
      const resp = await apiFetch('/auth/me/availability', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      showToast(resp.message, 'success');
      document.getElementById('config-availability-status')
        .classList.toggle('hidden', !toggle.checked);
      Auth.setUser({
        ...user,
        unavailable_for_notes: toggle.checked,
        substitute_director_id: payload.substitute_director_id,
      });
      renderGlobalAvailabilityBanner();
    } catch (e) {
      toggle.checked = !toggle.checked;
      showToast(e.message, 'error');
    }
  }

  toggle.addEventListener('change', applyChange);
  if (subSel) subSel.addEventListener('change', applyChange);
}

function renderGlobalAvailabilityBanner() {
  // Banner amarelo no topo do conteudo quando o usuario marcou indisponivel
  const user = Auth.getUser();
  const content = document.querySelector('.content');
  if (!content) return;
  let banner = document.getElementById('global-availability-banner');
  if (user?.unavailable_for_notes) {
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'global-availability-banner';
      banner.className = 'alert-banner alert-warning';
      banner.style.marginBottom = '1rem';
      banner.innerHTML =
        '<strong>Voce esta indisponivel para receber novas notas.</strong> ' +
        '<a href="/configuracoes" style="color:inherit;text-decoration:underline">Reativar</a>';
      content.prepend(banner);
    }
  } else if (banner) {
    banner.remove();
  }
}

// initChangePasswordPage movida para app/static/js/password.js (P2-1
// auditoria). Acesso via window.Economart.password.initChange().

let invoiceListState = {
  page: 1,
  perPage: 20,
  pages: 1,
  status: '',
  search: '',
  fromDate: '',
  toDate: '',
  dueFrom: '',
  dueTo: '',
  minAmount: '',
  maxAmount: '',
  createdBy: '',
  supplier: '',
  departmentId: '',
};
let _invoicesSearchDebounce = null;

async function initInvoicesList() {
  // CONTAS_A_PAGAR e FINANCE nao criam notas — esconde o botao "Nova Nota".
  const _u = Auth.getUser();
  if (_u && ['CONTAS_A_PAGAR', 'FINANCE'].includes(_u.role)) {
    document.getElementById('btn-new-invoice')?.remove();
  }
  // Preferencia de per_page salva localmente
  try {
    const saved = parseInt(localStorage.getItem('invoices_per_page') || '0', 10);
    if ([20, 50, 100].includes(saved)) invoiceListState.perPage = saved;
  } catch {}
  const perpageEl = document.getElementById('pagination-perpage');
  if (perpageEl) perpageEl.value = String(invoiceListState.perPage);

  const triggerReload = () => {
    invoiceListState.page = 1;
    loadInvoicesList();
  };
  // Status (filtro principal)
  document.getElementById('status-filter')?.addEventListener('change', (event) => {
    invoiceListState.status = event.target.value;
    triggerReload();
  });
  // Busca textual com debounce de 300ms
  document.getElementById('invoices-search')?.addEventListener('input', (event) => {
    invoiceListState.search = event.target.value;
    clearTimeout(_invoicesSearchDebounce);
    _invoicesSearchDebounce = setTimeout(triggerReload, 300);
  });
  // Filtros avancados
  document.getElementById('invoices-from-date')?.addEventListener('change', (e) => {
    invoiceListState.fromDate = e.target.value; triggerReload();
  });
  document.getElementById('invoices-to-date')?.addEventListener('change', (e) => {
    invoiceListState.toDate = e.target.value; triggerReload();
  });
  document.getElementById('invoices-due-from')?.addEventListener('change', (e) => {
    invoiceListState.dueFrom = e.target.value; triggerReload();
  });
  document.getElementById('invoices-due-to')?.addEventListener('change', (e) => {
    invoiceListState.dueTo = e.target.value; triggerReload();
  });
  document.getElementById('invoices-min-amount')?.addEventListener('change', (e) => {
    invoiceListState.minAmount = e.target.value; triggerReload();
  });
  document.getElementById('invoices-max-amount')?.addEventListener('change', (e) => {
    invoiceListState.maxAmount = e.target.value; triggerReload();
  });
  document.getElementById('invoices-created-by')?.addEventListener('input', (e) => {
    invoiceListState.createdBy = e.target.value;
    clearTimeout(_invoicesSearchDebounce);
    _invoicesSearchDebounce = setTimeout(triggerReload, 300);
  });
  document.getElementById('invoices-supplier')?.addEventListener('input', (e) => {
    invoiceListState.supplier = e.target.value;
    clearTimeout(_invoicesSearchDebounce);
    _invoicesSearchDebounce = setTimeout(triggerReload, 300);
  });
  document.getElementById('invoices-department')?.addEventListener('change', (e) => {
    invoiceListState.departmentId = e.target.value; triggerReload();
  });
  // Mostrar/esconder filtros avancados
  document.getElementById('invoices-toggle-advanced')?.addEventListener('click', () => {
    document.getElementById('invoices-advanced')?.classList.toggle('hidden');
  });
  // Limpar todos os filtros
  document.getElementById('invoices-clear-filters')?.addEventListener('click', () => {
    invoiceListState = { ...invoiceListState, search: '', fromDate: '', toDate: '', dueFrom: '', dueTo: '', minAmount: '', maxAmount: '', createdBy: '', supplier: '', departmentId: '', status: '' };
    ['invoices-search', 'invoices-from-date', 'invoices-to-date', 'invoices-due-from', 'invoices-due-to', 'invoices-min-amount', 'invoices-max-amount', 'invoices-created-by', 'invoices-supplier', 'invoices-department'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    const statusEl = document.getElementById('status-filter');
    if (statusEl) statusEl.value = '';
    triggerReload();
  });

  // Paginacao
  document.getElementById('prev-page')?.addEventListener('click', () => {
    if (invoiceListState.page > 1) {
      invoiceListState.page -= 1;
      loadInvoicesList();
    }
  });
  document.getElementById('next-page')?.addEventListener('click', () => {
    if (invoiceListState.page < invoiceListState.pages) {
      invoiceListState.page += 1;
      loadInvoicesList();
    }
  });
  const jumpEl = document.getElementById('pagination-jump');
  if (jumpEl) {
    jumpEl.addEventListener('change', () => {
      const n = parseInt(jumpEl.value, 10);
      if (!n || n < 1) return;
      const target = Math.min(n, invoiceListState.pages);
      invoiceListState.page = target;
      jumpEl.value = '';
      loadInvoicesList();
    });
  }
  if (perpageEl) {
    perpageEl.addEventListener('change', () => {
      invoiceListState.perPage = parseInt(perpageEl.value, 10) || 20;
      try { localStorage.setItem('invoices_per_page', String(invoiceListState.perPage)); } catch {}
      invoiceListState.page = 1;
      loadInvoicesList();
    });
  }

  // Carrega setores pro select (so admins enxergam, mas o endpoint /api/admin/departments
  // exige role admin — pra outros perfis, usa um fallback derivado das proprias notas).
  await populateDepartmentFilter();

  await loadInvoicesList();
}

async function populateDepartmentFilter() {
  const sel = document.getElementById('invoices-department');
  if (!sel) return;
  try {
    const me = Auth.getUser();
    let depts = [];
    if (me?.role === 'ADMIN') {
      depts = await apiFetch('/api/admin/departments');
    } else {
      // Outros perfis: deriva da lista atual de notas (uma amostra pequena
      // ja cobre os setores acessiveis). Evita expor /api/admin/departments.
      const sample = await apiFetch('/api/invoices/?per_page=100');
      const seen = new Map();
      (sample.items || []).forEach((it) => {
        if (it.department_name) seen.set(it.department_name, { id: it.department_name, name: it.department_name });
      });
      depts = Array.from(seen.values());
    }
    depts.forEach((d) => {
      const opt = document.createElement('option');
      // Admin: usa id real; outros perfis nao tem o id, entao filtro
      // permanece desabilitado pra eles
      opt.value = me?.role === 'ADMIN' ? d.id : '';
      opt.textContent = d.name;
      if (me?.role !== 'ADMIN') opt.disabled = true;
      sel.appendChild(opt);
    });
    if (me?.role !== 'ADMIN' && depts.length === 0) {
      sel.disabled = true;
    }
  } catch {
    sel.disabled = true;
  }
}

function renderInvoicesSkeleton(rows = 8) {
  const el = document.getElementById('invoices-table');
  if (!el) return;
  const rowHtml = `
    <tr>
      <td><span class="skeleton-line w-60"></span></td>
      <td><span class="skeleton-line w-80"></span></td>
      <td><span class="skeleton-line w-40"></span></td>
      <td><span class="skeleton-line w-40"></span></td>
      <td><span class="skeleton-line w-40"></span></td>
      <td><span class="skeleton-line w-60"></span></td>
      <td><span class="skeleton-line w-40"></span></td>
    </tr>`;
  el.innerHTML = `<table class="skeleton-table" aria-busy="true">
    <caption class="sr-only">Carregando notas fiscais</caption>
    <tbody>${rowHtml.repeat(rows)}</tbody>
  </table>`;
}

async function loadInvoicesList() {
  // Skeleton enquanto o request voa — feedback imediato
  renderInvoicesSkeleton(Math.min(invoiceListState.perPage, 12));

  const params = new URLSearchParams({
    page: invoiceListState.page,
    per_page: invoiceListState.perPage,
  });
  if (invoiceListState.status) params.set('status', invoiceListState.status);
  if (invoiceListState.search) params.set('search', invoiceListState.search);
  if (invoiceListState.fromDate) params.set('from_date', invoiceListState.fromDate);
  if (invoiceListState.toDate) params.set('to_date', invoiceListState.toDate);
  if (invoiceListState.dueFrom) params.set('due_from', invoiceListState.dueFrom);
  if (invoiceListState.dueTo) params.set('due_to', invoiceListState.dueTo);
  if (invoiceListState.minAmount) params.set('min_amount', invoiceListState.minAmount);
  if (invoiceListState.maxAmount) params.set('max_amount', invoiceListState.maxAmount);
  if (invoiceListState.createdBy) params.set('created_by', invoiceListState.createdBy);
  if (invoiceListState.supplier) params.set('supplier', invoiceListState.supplier);
  if (invoiceListState.departmentId) params.set('department_id', invoiceListState.departmentId);

  let data;
  try {
    data = await apiFetch(`/api/invoices/?${params.toString()}`);
  } catch (e) {
    const el = document.getElementById('invoices-table');
    if (el) el.innerHTML = `<p class="text-muted">Erro ao carregar: ${escapeHtml(e.message || 'tente novamente')}</p>`;
    return;
  }
  invoiceListState.pages = data.pages || 1;
  document.getElementById('page-indicator').textContent = `Pagina ${data.page} de ${invoiceListState.pages}`;
  document.getElementById('prev-page').disabled = data.page <= 1;
  document.getElementById('next-page').disabled = data.page >= invoiceListState.pages;
  const jumpEl = document.getElementById('pagination-jump');
  if (jumpEl) jumpEl.max = String(Math.max(invoiceListState.pages, 1));

  // Faixa exibida (ex: "Mostrando 21–40 de 1.234")
  const pageStart = data.total === 0 ? 0 : (data.page - 1) * invoiceListState.perPage + 1;
  const pageEnd = Math.min(data.page * invoiceListState.perPage, data.total);
  const infoEl = document.getElementById('pagination-info');
  if (infoEl) {
    infoEl.textContent = data.total
      ? `Mostrando ${pageStart}–${pageEnd} de ${data.total.toLocaleString('pt-BR')}`
      : 'Nenhuma nota encontrada com os filtros atuais.';
  }

  const countEl = document.getElementById('invoices-count');
  if (countEl) {
    countEl.textContent = data.total != null
      ? `${data.total.toLocaleString('pt-BR')} nota${data.total === 1 ? '' : 's'}`
      : '';
  }
  const totalizerEl = document.getElementById('invoices-totalizer');
  if (totalizerEl) {
    const count = data.total || 0;
    const sum = data.total_amount || 0;
    totalizerEl.textContent = `${count.toLocaleString('pt-BR')} nota${count === 1 ? '' : 's'} | Valor total: ${formatCurrency(sum)}`;
  }
  renderInvoicesTable(data.items);
}

function renderInvoicesTable(items) {
  const el = document.getElementById('invoices-table');
  if (!items.length) {
    el.innerHTML = '<p class="text-muted">Nenhuma nota encontrada.</p>';
    return;
  }
  el.innerHTML = `<table class="table">
    <caption class="sr-only">Notas fiscais cadastradas</caption>
    <thead><tr><th scope="col">Numero</th><th scope="col">Setor</th><th scope="col">Valor</th><th scope="col">Emissao</th><th scope="col">Vencimento</th><th scope="col">Status</th><th scope="col">Acoes</th></tr></thead>
    <tbody>${items.map((item) => {
      const canEdit = ['RASCUNHO', 'REPROVADO_GESTOR', 'REPROVADO_DIRETOR'].includes(item.status);
      // Excluivel: rascunho ou reprovada
      const canDelete = canEdit;
      const rejected = item.status.startsWith('REPROVADO');
      return `<tr class="${rejected ? 'rejected-row' : ''}">
        <td>${rejected ? '! ' : ''}${escapeHtml(item.invoice_number)}</td>
        <td>${escapeHtml(item.department_name || '-')}</td>
        <td>${formatCurrency(item.amount)}</td>
        <td>${formatDate(item.issue_date)}</td>
        <td>${formatDate(item.due_date)}</td>
        <td>${statusBadge(item.status)}${(item.comments_count || 0) > 0 ? ` <span class="status-badge" style="background:#fff3cd;color:#856404;margin-left:4px" title="${item.comments_count} comentario${item.comments_count === 1 ? '' : 's'}">💬 ${item.comments_count}</span>` : ''}</td>
        <td class="table-actions">
          <button class="btn btn-ghost btn-sm" data-drawer="${escapeHtml(item.id)}">Ver</button>
          ${canEdit ? `<a class="btn btn-ghost btn-sm" href="/invoices/${item.id}/edit">Editar</a>` : ''}
          ${canDelete ? `<button class="btn btn-danger btn-sm" data-action="delete" data-id="${item.id}">Excluir</button>` : ''}
        </td>
      </tr>`;
    }).join('')}</tbody></table>`;
  el.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', () => handleInvoiceAction(button.dataset.action, button.dataset.id));
  });
}

async function handleInvoiceAction(action, invoiceId) {
  if (action === 'delete') {
    if (!(await confirmAction('Excluir esta nota?'))) return;
    await apiFetch(`/api/invoices/${invoiceId}`, { method: 'DELETE' });
    showToast('Nota excluida.', 'success');
    await loadInvoicesList();
  }
}

// ─── CPF/CNPJ helpers (espelho dos do backend) ──────────────────────────────

// Helpers de CPF/CNPJ (stripDocDigits, validateCPF, validateCNPJ,
// formatDocument) movidos para app/static/js/documents.js (P2-1 auditoria).
// Acesso via window.* (alias) ou window.Economart.documents.*.
// documents.js carrega ANTES de app.js.

function setupSupplierDocField() {
  const input = document.getElementById('supplier-document');
  const status = document.getElementById('supplier-doc-status');
  const nameInput = document.getElementById('supplier-name');
  const legalNameInput = document.getElementById('supplier-legal-name');
  if (!input) return;

  let debounce = null;

  const update = async () => {
    const raw = input.value;
    const digits = stripDocDigits(raw);
    // Aplica mascara visual conforme digita
    if (digits.length <= 14) {
      input.value = formatDocument(digits);
    }
    if (digits.length === 11) {
      if (validateCPF(digits)) {
        status.textContent = 'CPF valido.';
        status.style.color = 'var(--success)';
      } else {
        status.textContent = 'CPF invalido. Verifique os digitos.';
        status.style.color = 'var(--error)';
      }
    } else if (digits.length === 14) {
      if (validateCNPJ(digits)) {
        status.textContent = 'CNPJ valido. Buscando nome...';
        status.style.color = 'var(--success)';
        // Consulta API de CNPJ
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
          try {
            const data = await apiFetch(`/api/invoices/lookup-cnpj/${digits}`);
            if (data?.razao_social || data?.nome_fantasia) {
              nameInput.value = data.nome_fantasia || data.razao_social || '';
              legalNameInput.value = data.razao_social || '';
              status.textContent = 'CNPJ valido. Dados do fornecedor preenchidos.';
            } else {
              status.textContent = 'CNPJ valido. Nao localizamos a razao social — preencha manualmente.';
            }
          } catch (e) {
            status.textContent = 'CNPJ valido. Nao foi possivel buscar a razao social agora — preencha manualmente.';
            status.style.color = 'var(--warning)';
          }
        }, 400);
      } else {
        status.textContent = 'CNPJ invalido. Verifique os digitos.';
        status.style.color = 'var(--error)';
      }
    } else if (digits.length === 0) {
      status.textContent = 'Digite o CPF (11) ou CNPJ (14).';
      status.style.color = 'var(--text-muted)';
    } else {
      status.textContent = `Faltam ${digits.length < 11 ? 11 - digits.length : 14 - digits.length} digitos.`;
      status.style.color = 'var(--text-muted)';
    }
  };

  input.addEventListener('input', update);
}


function setupInvoiceFileInput() {
  const dropZone = document.getElementById('drop-zone');
  const input = document.getElementById('invoice-file');
  const label = document.getElementById('selected-file-name');
  if (!dropZone || !input) return;
  const MAX_FILES = 5;

  const updateName = () => {
    const files = Array.from(input.files || []);
    if (!files.length) {
      label.textContent = 'Nenhum arquivo selecionado';
      return;
    }
    if (files.length === 1) {
      label.textContent = files[0].name;
    } else {
      label.textContent = `${files.length} arquivos: ${files.map(f => f.name).join(', ')}`;
    }
  };
  ['dragenter', 'dragover'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove('dragover');
    });
  });
  dropZone.addEventListener('drop', (event) => {
    const dropped = Array.from(event.dataTransfer.files || []);
    const pdfs = dropped.filter((f) =>
      f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
    );
    if (!pdfs.length) {
      showToast('Selecione arquivos PDF.', 'error');
      return;
    }
    if (pdfs.length > MAX_FILES) {
      showToast(`Maximo ${MAX_FILES} arquivos por nota.`, 'error');
      return;
    }
    const transfer = new DataTransfer();
    pdfs.forEach((f) => transfer.items.add(f));
    input.files = transfer.files;
    updateName();
  });
  input.addEventListener('change', () => {
    if ((input.files?.length || 0) > MAX_FILES) {
      showToast(`Maximo ${MAX_FILES} arquivos. Selecione menos.`, 'error');
      input.value = '';
    }
    updateName();
  });
}

async function initInvoiceForm(mode) {
  const description = document.getElementById('description');
  description?.addEventListener('input', () => {
    document.getElementById('description-count').textContent = description.value.length;
  });
  setupInvoiceFileInput();
  setupSupplierDocField();

  const user = Auth.getUser();
  // Diretor: pula a etapa de escolher diretor (vai direto ao Financeiro).
  // Funcionario com submit_directly_to_director ou Gestor: mostra picker.
  if (user?.role === 'DIRECTOR') {
    const submitBtn = document.getElementById('invoice-submit-btn');
    if (submitBtn) submitBtn.textContent = 'Criar e Enviar ao Financeiro';
  } else if (user?.submit_directly_to_director || user?.role === 'MANAGER') {
    const dirGroup = document.getElementById('director-select-group');
    if (dirGroup) dirGroup.style.display = '';
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'director-list', 'chosen-director-id');
    } catch {
      const el = document.getElementById('director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }

  if (mode === 'edit') {
    const invoice = await apiFetch(invoiceApiPath(getInvoiceIdFromPath()));
    if (!['RASCUNHO', 'REPROVADO_GESTOR', 'REPROVADO_DIRETOR'].includes(invoice.status)) {
      showToast('Esta nota nao pode ser editada neste status.', 'error');
      window.location.href = `/invoices/${invoice.id}`;
      return;
    }
    fillInvoiceForm(invoice);
    const submitBtn = document.getElementById('invoice-submit-btn');
    if (submitBtn) submitBtn.textContent = 'Salvar e Reenviar';
    document.getElementById('btn-save-draft')?.classList.add('hidden');
  }

  document.getElementById('btn-save-draft')?.addEventListener('click', () => saveInvoice(null, mode, false));
  document.getElementById('invoice-form')?.addEventListener('submit', (event) => saveInvoice(event, mode, true));
}

function fillInvoiceForm(invoice) {
  document.getElementById('invoice-number').value = invoice.invoice_number;
  document.getElementById('amount').value = invoice.amount;
  document.getElementById('issue-date').value = invoice.issue_date;
  document.getElementById('due-date').value = invoice.due_date;
  document.getElementById('description').value = invoice.description;
  document.getElementById('description-count').textContent = invoice.description.length;
  document.getElementById('bank-details').value = invoice.bank_details || '';
  // Fornecedor
  const docInput = document.getElementById('supplier-document');
  if (docInput && invoice.supplier_document) {
    docInput.value = formatDocument(invoice.supplier_document);
    docInput.dispatchEvent(new Event('input'));  // dispara validacao + status
  }
  const nameInput = document.getElementById('supplier-name');
  const legalInput = document.getElementById('supplier-legal-name');
  if (nameInput) nameInput.value = invoice.supplier_name || '';
  if (legalInput) legalInput.value = invoice.supplier_legal_name || '';
  renderExistingAttachmentsList(invoice);
}

function renderExistingAttachmentsList(invoice) {
  const group = document.getElementById('existing-attachments-group');
  const list = document.getElementById('existing-attachments-list');
  if (!group || !list) return;
  const attachments = invoice.attachments || [];
  if (!attachments.length) {
    group.classList.add('hidden');
    return;
  }
  group.classList.remove('hidden');
  list.innerHTML = attachments.map((att) => {
    const sizeKb = (att.size_bytes / 1024).toFixed(0);
    const canRemove = attachments.length > 1;
    return `<div class="attachment-row">
      <a href="/api/invoices/${escapeHtml(invoice.id)}/attachments/${escapeHtml(att.id)}" target="_blank" rel="noopener">
        ${escapeHtml(att.drive_file_name || 'anexo.pdf')}
      </a>
      <span class="text-muted" style="font-size:.8rem">${sizeKb} KB</span>
      ${canRemove ? `<button type="button" class="btn btn-ghost btn-sm" data-remove-attachment="${escapeHtml(att.id)}">Remover</button>` : ''}
    </div>`;
  }).join('');
  list.querySelectorAll('[data-remove-attachment]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const attId = btn.dataset.removeAttachment;
      if (!(await confirmAction('Remover este anexo?'))) return;
      try {
        await apiFetch(`/api/invoices/${invoice.id}/attachments/${attId}`, { method: 'DELETE' });
        showToast('Anexo removido.', 'success');
        const fresh = await apiFetch(`/api/invoices/${invoice.id}`);
        renderExistingAttachmentsList(fresh);
      } catch (e) {
        showToast(e.message, 'error');
      }
    });
  });
}

async function saveInvoice(event, mode, submitNow = true) {
  if (event) event.preventDefault();
  const issueDate = document.getElementById('issue-date').value;
  const dueDate = document.getElementById('due-date').value;
  const description = document.getElementById('description').value.trim();
  const supplierDocRaw = document.getElementById('supplier-document')?.value || '';
  const supplierDoc = stripDocDigits(supplierDocRaw);
  const filesInput = document.getElementById('invoice-file');
  const files = Array.from(filesInput?.files || []);
  if (dueDate < issueDate) return showToast('Vencimento nao pode ser anterior a emissao.', 'error');
  if (description.length < 10) return showToast('Descricao deve ter ao menos 10 caracteres.', 'error');
  // Validacao CPF/CNPJ
  if (!supplierDoc) return showToast('Informe o CPF ou CNPJ do fornecedor.', 'error');
  const isValidDoc = supplierDoc.length === 11 ? validateCPF(supplierDoc) :
                     supplierDoc.length === 14 ? validateCNPJ(supplierDoc) : false;
  if (!isValidDoc) return showToast('CPF/CNPJ invalido. Verifique os digitos.', 'error');
  const invalidFile = files.find((f) => !f.name.toLowerCase().endsWith('.pdf'));
  if (invalidFile) return showToast(`'${invalidFile.name}' nao e um PDF.`, 'error');
  // Pelo menos 1 PDF obrigatorio para novas notas
  if (mode !== 'edit' && files.length === 0) {
    return showToast('Anexe ao menos um PDF (nota fiscal) antes de continuar.', 'error');
  }
  if (files.length > 5) return showToast('Maximo 5 arquivos por nota.', 'error');
  const form = new FormData();
  form.append('invoice_number', document.getElementById('invoice-number').value.trim());
  form.append('amount', document.getElementById('amount').value);
  form.append('issue_date', issueDate);
  form.append('due_date', dueDate);
  form.append('description', description);
  form.append('bank_details', document.getElementById('bank-details').value.trim());
  form.append('supplier_document', supplierDoc);
  form.append('supplier_name', document.getElementById('supplier-name')?.value?.trim() || '');
  form.append('supplier_legal_name', document.getElementById('supplier-legal-name')?.value?.trim() || '');
  // FastAPI le 'files' (plural) como list[UploadFile]
  files.forEach((f) => form.append('files', f));
  if (mode !== 'edit') {
    form.append('submit_now', submitNow ? 'true' : 'false');
    const directorId = document.getElementById('chosen-director-id')?.value;
    if (directorId) form.append('director_id', directorId);
  }
  showLoading();
  try {
    const invoiceId = getInvoiceIdFromPath();
    const invoice = await apiFetch(mode === 'edit' ? `/api/invoices/${invoiceId}` : '/api/invoices/', {
      method: mode === 'edit' ? 'PATCH' : 'POST',
      body: form
    });
    const msg = mode === 'edit' ? 'Nota atualizada!' : submitNow ? 'Nota criada e enviada!' : 'Rascunho salvo!';
    showToast(msg, 'success');
    window.location.href = `/invoices/${invoice.id}`;
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    hideLoading();
  }
}

async function initInvoiceDetail() {
  const invoiceId = getInvoiceIdFromPath();
  const invoice = await apiFetch(invoiceApiPath(invoiceId));
  renderInvoiceDetail(invoice);
  if (invoice.has_attachment) loadPdfInline(invoiceId);
  setupComments(invoiceId);
}

// ─── Comentarios na nota ──────────────────────────────────────────────
// Funcoes (_commentInitials, _commentDateLabel, renderComments,
// _normalizeCommentsResponse, setupComments) movidas para
// app/static/js/comments.js (P2-1 auditoria). Acesso via window.* (alias)
// ou window.Economart.comments.*. comments.js carrega DEPOIS de app.js.

function renderInvoiceAlerts(invoice, containerId) {
  // Banners contextuais (emissao antiga, vencimento curto).
  // Insere/atualiza dinamicamente acima do container alvo.
  const target = document.getElementById(containerId);
  if (!target) return;
  const alertsId = `${containerId}-alerts-banner`;
  let banner = document.getElementById(alertsId);
  const items = invoice?.alerts || [];
  if (!items.length) {
    if (banner) banner.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement('div');
    banner.id = alertsId;
    banner.className = 'alert-banner alert-warning';
    banner.style.marginBottom = '1rem';
    target.parentNode.insertBefore(banner, target);
  }
  banner.innerHTML = '<strong>Atencao:</strong><ul>' +
    items.map((m) => `<li>${escapeHtml(m)}</li>`).join('') + '</ul>';
}

function renderAttachmentsBlock(invoice, targetSelector) {
  // No-op: multi-anexo agora e mesclado pelo backend em PDF unico no
  // iframe principal. Mantido pra compat com chamadas antigas.
}

function renderInvoiceDetail(invoice) {
  document.getElementById('detail-title').textContent = `Nota ${invoice.invoice_number}`;
  document.getElementById('detail-subtitle').textContent = `Criada por ${invoice.created_by.name} em ${formatDateTime(invoice.created_at)}`;
  document.getElementById('detail-status').innerHTML = statusBadge(invoice.status);
  renderInvoiceAlerts(invoice, 'detail-grid');
  renderAttachmentsBlock(invoice, '#pdf-panel');
  const docLabel = invoice.supplier_document_type || 'CPF/CNPJ';
  const docFormatted = invoice.supplier_document ? formatDocument(invoice.supplier_document) : '-';
  const supplierLine = invoice.supplier_name
    ? `${invoice.supplier_name}${invoice.supplier_legal_name && invoice.supplier_legal_name !== invoice.supplier_name ? ` (${invoice.supplier_legal_name})` : ''}`
    : '-';
  document.getElementById('detail-grid').innerHTML = [
    ['Valor', formatCurrency(invoice.amount)], ['Emissao', formatDate(invoice.issue_date)],
    ['Vencimento', formatDate(invoice.due_date)], ['Criador', invoice.created_by.name],
    ['Setor', invoice.department_name || '-'],
    [docLabel, docFormatted], ['Fornecedor', supplierLine],
    ['Descricao', invoice.description],
    ['Dados bancarios', invoice.bank_details || '-']
  ].map(([label, value]) => `<div class="detail-item"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`).join('');
  // Reprovacao MAIS RECENTE — se a nota foi reprovada, editada e reprovada de
  // novo, o usuario precisa ver o motivo atual, nao o primeiro.
  const rejection = [...invoice.history].reverse().find((item) => item.action.startsWith('REJECTED'));
  const box = document.getElementById('rejection-box');
  if (box) {
    if (rejection) {
      box.innerHTML = `<strong>Motivo da reprovacao:</strong> ${escapeHtml(rejection.comment || 'Sem comentario.')}`;
      box.classList.remove('hidden');
    } else {
      box.classList.add('hidden');
    }
  }
  renderDetailActions(invoice);
  renderTimeline(invoice.history);
}

async function renderDetailActions(invoice) {
  const actions = document.getElementById('detail-actions');
  if (!actions) return;
  const user = Auth.getUser();
  const isDirect = Boolean(user?.submit_directly_to_director);
  const buttons = [];
  if (invoice.can_cancel) {
    buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
  }
  if (invoice.status === 'RASCUNHO') {
    buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
    if (isDirect) {
      buttons.push('<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>');
    } else {
      buttons.push('<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
    }
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }
  if (invoice.status.startsWith('REPROVADO')) {
    buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }
  // Reimpressao do comprovante para notas LANCADAS — disponivel para
  // Contas a Pagar, Financeiro e Admin (ja autenticados). A 1a impressao
  // (status APROVADO) continua exclusiva do Financeiro pela pagina dele.
  if (invoice.status === 'PAGO' && ['CONTAS_A_PAGAR', 'FINANCE', 'ADMIN'].includes(user?.role)) {
    buttons.push('<button class="btn btn-primary" data-action="reprint">Reimprimir comprovante</button>');
  }
  let directorHtml = '';
  if (invoice.status === 'RASCUNHO' && isDirect) {
    directorHtml = '<div class="form-group" id="detail-director-wrap"><label class="form-label">Enviar para o diretor:</label><div id="detail-director-list" class="director-list"><p class="text-muted">Carregando...</p></div><input type="hidden" id="detail-chosen-director"></div>';
  }
  actions.innerHTML = directorHtml + buttons.join('');
  if (invoice.status === 'RASCUNHO' && isDirect) {
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'detail-director-list', 'detail-chosen-director');
    } catch {
      const el = document.getElementById('detail-director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }
  actions.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        if (button.dataset.action === 'submit') {
          const updated = await submitInvoiceWithDuplicateCheck(invoice.id);
          if (!updated) return;
          showToast('Nota enviada para o gestor.', 'success');
          renderInvoiceDetail(updated);
          if (updated.has_attachment) loadPdfInline(updated.id);
        } else if (button.dataset.action === 'submit-direct') {
          const dirId = document.getElementById('detail-chosen-director')?.value;
          if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
          const updated = await submitInvoiceWithDuplicateCheck(invoice.id, dirId);
          if (!updated) return;
          showToast('Nota enviada para o diretor.', 'success');
          renderInvoiceDetail(updated);
          if (updated.has_attachment) loadPdfInline(updated.id);
        } else if (button.dataset.action === 'cancel') {
          if (!(await confirmAction('Cancelar esta nota? Ela voltara para rascunho.'))) return;
          const updated = await apiFetch(`/api/invoices/${invoice.id}/cancel`, { method: 'POST' });
          showToast('Nota cancelada.', 'success');
          renderInvoiceDetail(updated);
        } else if (button.dataset.action === 'delete') {
          if (!(await confirmAction('Excluir esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}`, { method: 'DELETE' });
          window.location.href = '/invoices';
        } else if (button.dataset.action === 'reprint') {
          const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/print`);
          if (ok) showToast('Comprovante gerado.', 'success');
        }
      } catch (e) { showToast(e.message, 'error'); }
    });
  });
}

function renderTimeline(history) {
  const icons = { CREATED: '+', SUBMITTED: '>', APPROVED_MANAGER: '✓', REJECTED_MANAGER: 'x', APPROVED_DIRECTOR: '✓', REJECTED_DIRECTOR: 'x', MARKED_PAID: '$' };
  const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Envio cancelado', APPROVED_MANAGER: 'Aprovada pelo gestor', REJECTED_MANAGER: 'Reprovada pelo gestor', APPROVED_DIRECTOR: 'Aprovada pelo diretor', REJECTED_DIRECTOR: 'Reprovada pelo diretor', MARKED_PAID: 'Marcada como lancada', PRINTED: 'Impressa', TRANSFERRED_DIRECTOR: 'Repassada a outro diretor' };
  const el = document.getElementById('invoice-timeline');
  if (!el) return;
  el.innerHTML = history.map((item) => `
    <div class="timeline-item"><div class="timeline-icon">${icons[item.action] || '-'}</div><div>
      <strong>${labels[item.action] || item.action}</strong>
      <div class="timeline-meta">${escapeHtml(item.user.name)} - ${formatDateTime(item.timestamp)}</div>
      ${item.comment ? `<p>${escapeHtml(item.comment)}</p>` : ''}
    </div></div>`).join('');
}

// ── PDF helpers ──────────────────────────────────────────────────────────────

async function fetchAndOpenPdf(url, options = {}) {
  // POST /mark-paid foi separado de GET /print pra que abrir/recarregar o
  // comprovante (idempotente) nao dispare lancamento financeiro. Quem chama
  // este helper passa { method: 'POST' } quando a intencao e LANCAR a nota.
  const method = (options.method || 'GET').toUpperCase();
  showLoading();
  try {
    const token = Auth.getToken();
    const headers = token ? { Authorization: `Bearer ${token}` } : {};
    const resp = await fetch(url, { method, headers });
    if (!resp.ok) {
      let detail = 'Erro ao gerar PDF';
      try { detail = (await resp.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    window.open(blobUrl, '_blank');
    return true;
  } catch (e) {
    showToast(e.message, 'error');
    return false;
  } finally {
    hideLoading();
  }
}

/** Retorna URL + method certo conforme status da nota:
 *  - APROVADO -> POST /mark-paid (lanca + retorna PDF)
 *  - PAGO     -> GET  /print     (reimpressao, sem efeito)
 *  Usar nos 4 botoes do financeiro/drawer pra evitar duplicar a logica. */
function _printOrMarkPaidEndpoint(invoice) {
  if (invoice.status === 'APROVADO') {
    return { url: `/api/invoices/${invoice.id}/mark-paid`, method: 'POST' };
  }
  return { url: `/api/invoices/${invoice.id}/print`, method: 'GET' };
}

// ── PDF inline + director selection helpers ─────────────────────────────────

// Estado do viewer PDF (zoom). Rotacao foi removida — o iframe nativo do
// browser ja oferece rotate proprio no viewer interno, e nosso transform
// CSS no iframe inteiro causava bug visual: ao rodar 90 graus o aspect
// ratio mudava (vertical -> horizontal) e o iframe saia pra fora do
// container por causa do overflow:hidden, "sumindo" da tela. A cada 4
// cliques (360 graus) voltava ao normal. Reportado pelo usuario.
let _pdfViewerState = { zoom: 1 };

function _applyPdfTransform() {
  const iframe = document.getElementById('pdf-iframe');
  if (!iframe) return;
  iframe.style.transform = `scale(${_pdfViewerState.zoom})`;
  const label = document.getElementById('pdf-zoom-label');
  if (label) label.textContent = `${Math.round(_pdfViewerState.zoom * 100)}%`;
}

function _setupPdfToolbar() {
  const panel = document.getElementById('pdf-panel');
  if (!panel || panel.dataset.toolbarReady) return;
  panel.dataset.toolbarReady = '1';
  document.getElementById('pdf-zoom-in')?.addEventListener('click', () => {
    _pdfViewerState.zoom = Math.min(_pdfViewerState.zoom + 0.1, 3);
    _applyPdfTransform();
  });
  document.getElementById('pdf-zoom-out')?.addEventListener('click', () => {
    _pdfViewerState.zoom = Math.max(_pdfViewerState.zoom - 0.1, 0.4);
    _applyPdfTransform();
  });
  document.getElementById('pdf-fullscreen')?.addEventListener('click', () => {
    panel.classList.toggle('fullscreen');
  });
}

async function loadPdfInline(invoiceId) {
  const panel = document.getElementById('pdf-panel');
  if (!panel) return;
  try {
    const token = Auth.getToken();
    const resp = await fetch(`/api/invoices/${invoiceId}/attachment`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const iframe = document.getElementById('pdf-iframe');
    const link = document.getElementById('pdf-download-link');
    if (iframe) iframe.src = url;
    if (link) link.href = url;
    panel.style.display = 'block';
    _pdfViewerState = { zoom: 1 };
    _applyPdfTransform();
    _setupPdfToolbar();
  } catch {}
}

function renderDirectorList(directors, containerId, hiddenInputId) {
  const container = document.getElementById(containerId);
  const hiddenInput = hiddenInputId ? document.getElementById(hiddenInputId) : null;
  if (!container) return;
  if (!directors || !directors.length) {
    container.innerHTML = '<p class="text-muted">Nenhum diretor disponivel.</p>';
    return;
  }
  container.innerHTML = directors.map((d) => `
    <div class="director-card" data-id="${escapeHtml(d.id)}">
      <strong>${escapeHtml(d.name)}</strong>
      ${d.is_primary
        ? '<span class="badge-primary-sector">Responsavel pelo seu setor</span>'
        : '<span class="badge-other-sector">Nao e o diretor padrao deste setor</span>'}
    </div>`).join('');
  const primary = directors.find((d) => d.is_primary) || directors[0];
  if (primary && hiddenInput) {
    hiddenInput.value = primary.id;
    container.querySelector(`[data-id="${primary.id}"]`)?.classList.add('selected');
  }
  container.querySelectorAll('.director-card').forEach((card) => {
    card.addEventListener('click', () => {
      container.querySelectorAll('.director-card').forEach((c) => c.classList.remove('selected'));
      card.classList.add('selected');
      if (hiddenInput) hiddenInput.value = card.dataset.id;
    });
  });
}

function pickDirectorModal(directors) {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal modal-wide">
        <h2>Encaminhar para diretor</h2>
        <p class="text-muted">Selecione o diretor responsavel pela aprovacao desta nota.</p>
        <div id="pick-director-list" class="director-list"></div>
        <input type="hidden" id="pick-director-id">
        <div class="modal-actions">
          <button class="btn btn-ghost" data-action="cancel">Cancelar</button>
          <button class="btn btn-primary" data-action="confirm">Encaminhar</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    renderDirectorList(directors, 'pick-director-list', 'pick-director-id');
    backdrop.addEventListener('click', (event) => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (!action) return;
      const dirId = document.getElementById('pick-director-id')?.value;
      backdrop.remove();
      resolve(action === 'confirm' && dirId ? dirId : null);
    });
  });
}

// ── Alerts ──────────────────────────────────────────────────────────────────

async function initAlertsPage() {
  const data = await apiFetch('/alerts/');
  const groups = [
    ['rejected', 'Suas notas reprovadas', 'error'],
    ['overdue', 'Vencidas', 'error'],
    ['due_72h', 'Vencem em 72h', 'warning'],
    ['old_emission', 'Emissao antiga', 'info'],
    ['pending_review', 'Aguardando revisao', 'info'],
  ];
  document.getElementById('alerts-page').innerHTML = groups.map(([key, title, type]) => {
    const items = data[key] || [];
    return `<section class="accordion-section"><button class="accordion-header ${type}" data-accordion>${title} (${items.length})</button><div class="accordion-body">${renderAlertTable(items)}</div></section>`;
  }).join('');
  document.querySelectorAll('[data-accordion]').forEach((button) => {
    button.addEventListener('click', () => button.closest('.accordion-section').classList.toggle('collapsed'));
  });
}

function renderAlertTable(items) {
  if (!items.length) return '<p class="text-muted">Nenhuma nota nesta categoria.</p>';
  return `<table class="table"><caption class="sr-only">Notas do grupo de alertas</caption><thead><tr><th scope="col">Numero</th><th scope="col">Valor</th><th scope="col">Emissao</th><th scope="col">Vencimento</th><th scope="col">Status</th><th scope="col">Acoes</th></tr></thead>
    <tbody>${items.map((item) => `<tr><td>${escapeHtml(item.invoice_number)}</td><td>${formatCurrency(item.amount)}</td><td>${formatDate(item.issue_date)}</td><td>${formatDate(item.due_date)}</td><td>${statusBadge(item.status)}</td><td><button class="btn btn-ghost btn-sm" data-drawer="${escapeHtml(item.id)}">Ver</button></td></tr>`).join('')}</tbody></table>`;
}

function isWithinDateRange(dateStr, from, to) {
  if (from && dateStr < from) return false;
  if (to && dateStr > to) return false;
  return true;
}

// ── Finance ──────────────────────────────────────────────────────────────────

async function loadFinanceInvoices(status = '') {
  const url = status ? `/api/invoices/?status=${status}&per_page=100` : '/api/invoices/?per_page=100';
  const data = await apiFetch(url);
  return data.items.sort((a, b) => a.due_date.localeCompare(b.due_date));
}

async function initFinanceQueue() {
  const state = { status: 'APROVADO', dueFrom: '', dueTo: '' };
  const filter = document.getElementById('finance-queue-filter');
  filter?.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      filter.querySelectorAll('button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.status = button.dataset.status;
      loadFinanceQueue();
    });
  });
  ['finance-due-from', 'finance-due-to'].forEach((id) => {
    document.getElementById(id)?.addEventListener('change', (event) => {
      if (id.endsWith('from')) state.dueFrom = event.target.value;
      else state.dueTo = event.target.value;
      loadFinanceQueue();
    });
  });
  document.getElementById('finance-clear-filter')?.addEventListener('click', () => {
    state.dueFrom = '';
    state.dueTo = '';
    document.getElementById('finance-due-from').value = '';
    document.getElementById('finance-due-to').value = '';
    loadFinanceQueue();
  });
  async function loadFinanceQueue() {
    const approved = await loadFinanceInvoices('APROVADO');
    document.getElementById('finance-pending-count').textContent = `${approved.length} pendentes`;
    const navCount = document.getElementById('finance-count-nav');
    if (navCount) {
      navCount.textContent = approved.length;
      navCount.classList.toggle('hidden', approved.length === 0);
    }
    const items = (state.status === 'APROVADO' ? approved : await loadFinanceInvoices('PAGO'))
      .filter((item) => isWithinDateRange(item.due_date, state.dueFrom, state.dueTo));
    renderFinanceQueue(items);
  }
  await loadFinanceQueue();
}

function renderFinanceQueue(items) {
  const el = document.getElementById('finance-queue-table');
  if (!items.length) {
    el.innerHTML = '<div class="alert-banner alert-info"><strong>Nenhuma nota nesta fila.</strong></div>';
    return;
  }
  el.innerHTML = `<table class="table"><caption class="sr-only">Fila financeira de notas</caption><thead><tr>
    <th scope="col">Numero</th><th scope="col">Criado por</th><th scope="col">Valor</th><th scope="col">Vencimento</th><th scope="col">Status</th><th scope="col">Acoes</th>
  </tr></thead><tbody>${items.map((item) => {
    const overdue = daysUntil(item.due_date) < 0 && item.status !== 'PAGO';
    return `<tr class="${overdue ? 'overdue-row' : ''}">
      <td>${escapeHtml(item.invoice_number)}</td>
      <td>${escapeHtml(item.created_by.name)}</td>
      <td>${formatCurrency(item.amount)}</td>
      <td>${daysBadge(item.due_date)}</td>
      <td>${statusBadge(item.status)}</td>
      <td><button class="btn btn-primary btn-sm" data-drawer="${escapeHtml(item.id)}">Abrir</button></td>
    </tr>`;
  }).join('')}</tbody></table>`;
}

async function initFinanceDetail() {
  const invoiceId = getInvoiceIdFromPath();
  const invoice = await apiFetch(invoiceApiPath(invoiceId));
  renderInvoiceDetail(invoice);
  renderFinanceActions(invoice);
  if (invoice.has_attachment) loadPdfInline(invoiceId);
}

function approvalLine(invoice, action, label) {
  const item = invoice.history.find((entry) => entry.action === action);
  const done = Boolean(item);
  return `<div class="timeline-item">
    <div class="timeline-icon ${done ? 'tl-ok' : 'tl-pending'}">${done ? '✓' : '·'}</div>
    <div>
      <strong>${label}</strong>
      <div class="timeline-meta">${done ? `${escapeHtml(item.user.name)} — ${formatDateTime(item.timestamp)}` : 'Pendente'}</div>
    </div>
  </div>`;
}

function renderFinanceActions(invoice) {
  const actions = document.getElementById('finance-actions');
  if (!actions) return;

  // Monta timeline de aprovacao financeira
  const printedEntry = invoice.history.slice().reverse().find((h) => h.action === 'PRINTED');
  const printedLine = printedEntry
    ? `<div class="timeline-item">
        <div class="timeline-icon tl-print">🖨</div>
        <div>
          <strong>Comprovante impresso</strong>
          <div class="timeline-meta">${escapeHtml(printedEntry.user.name)} — ${formatDateTime(printedEntry.timestamp)}</div>
        </div>
       </div>`
    : '';
  const timelineEl = document.getElementById('invoice-timeline');
  if (timelineEl) {
    timelineEl.innerHTML = [
      approvalLine(invoice, 'CREATED', 'Criado por'),
      approvalLine(invoice, 'APPROVED_MANAGER', 'Aprovado pelo Gestor'),
      approvalLine(invoice, 'APPROVED_DIRECTOR', 'Aprovado pelo Diretor'),
      printedLine
    ].join('');
  }

  // Nota ja lancada
  if (invoice.status === 'PAGO') {
    actions.innerHTML = `
      <div class="receipt-card receipt-paid">
        <div class="receipt-card-icon">✓</div>
        <div class="receipt-card-body">
          <strong>Nota lancada</strong>
          <span class="text-muted">${formatDateTime(invoice.paid_at)}</span>
        </div>
        <button class="btn btn-ghost btn-sm" id="print-invoice-btn">Re-imprimir comprovante</button>
      </div>`;
    document.getElementById('print-invoice-btn')?.addEventListener('click', async () => {
      await fetchAndOpenPdf(`/api/invoices/${invoice.id}/print`);
    });
    return;
  }

  if (invoice.status !== 'APROVADO') {
    actions.innerHTML = '<p class="text-muted">Nenhuma acao financeira disponivel para este status.</p>';
    return;
  }

  // Nota aprovada — pronta para impressao e lancamento
  const lastPrintHtml = printedEntry
    ? `<p class="receipt-last-print">Ultima impressao: ${formatDateTime(printedEntry.timestamp)} por ${escapeHtml(printedEntry.user.name)}</p>`
    : '';

  actions.innerHTML = `
    <div class="receipt-card">
      <div class="receipt-card-icon">🖨</div>
      <div class="receipt-card-body">
        <strong>Comprovante de Recebimento</strong>
        <p>Gera um PDF com trilha de aprovacao completa (Gestor + Diretor), QR code de autenticidade e o PDF original da nota. Ao imprimir, o sistema registra automaticamente o recebimento pelo setor financeiro.</p>
        ${lastPrintHtml}
      </div>
      <div class="receipt-card-actions">
        <button class="btn btn-primary" id="print-invoice-btn">Imprimir e Confirmar Recebimento</button>
      </div>
    </div>`;

  document.getElementById('print-invoice-btn')?.addEventListener('click', async () => {
    // APROVADO -> POST /mark-paid: lanca a nota explicitamente e devolve o PDF.
    // Antes era GET /print, mas leitura nao deveria mutar estado (P0 auditoria).
    if (!(await confirmAction('Confirmar recebimento e lancar a nota? Esta acao sera registrada.'))) return;
    const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/mark-paid`, { method: 'POST' });
    if (ok) {
      showToast('Comprovante gerado. Recebimento registrado no sistema.', 'success');
      setTimeout(() => window.location.reload(), 1800);
    }
  });
}

function daysUntil(dueDate) {
  const today = new Date(`${todayInBR()}T00:00:00`);
  const due   = new Date(`${dueDate}T00:00:00`);
  return Math.ceil((due - today) / 86400000);
}

function daysBadge(dueDate) {
  const days = daysUntil(dueDate);
  const cls = days > 7 ? 'days-ok' : days >= 3 ? 'days-warning' : 'days-danger';
  const label = days < 0 ? `${Math.abs(days)} dias vencida` : days === 0 ? 'vence hoje' : `${days} dias`;
  return `<span class="days-badge ${cls}">${label}</span>`;
}

// ── Review (manager / director) ──────────────────────────────────────────────

async function reviewInvoice(invoiceId, action, endpoint, directorId = null) {
  let comment = null;
  if (action === 'APPROVE') {
    // Sem confirmacao dupla pra aprovacao — usuario ja clicou no botao
    // explicito 'Aprovar'. Reprovacao continua exigindo motivo (modal abaixo).
  } else {
    comment = await rejectReasonModal();
    if (!comment) return false;
  }
  try {
    const body = { action, comment };
    if (directorId) body.director_id = directorId;
    await apiFetch(endpoint, {
      method: 'POST',
      body: JSON.stringify(body)
    });
    showToast(action === 'APPROVE' ? 'Nota aprovada com sucesso.' : 'Nota reprovada com sucesso.', 'success');
    return true;
  } catch (error) {
    showToast(error.message, 'error');
    return false;
  }
}

async function initReviewQueue(role) {
  const state = { mode: 'pending' };
  const statusFilter = role === 'manager' ? 'AGUARDANDO_GESTOR' : 'AGUARDANDO_DIRETOR';
  const containerId = role === 'manager' ? 'manager-queue-table' : 'director-queue-table';
  const endpointPart = role === 'manager' ? 'review' : 'director-review';
  const detailPrefix = role === 'manager' ? '/manager/invoices' : '/director/invoices';
  const filter = document.getElementById(`${role}-queue-filter`);
  filter?.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      filter.querySelectorAll('button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.mode = button.dataset.mode;
      loadReviewQueue();
    });
  });

  async function loadReviewQueue() {
    const url = state.mode === 'pending' ? `/api/invoices/?status=${statusFilter}&per_page=100` : '/api/invoices/?per_page=100';
    const data = await apiFetch(url);
    const pendingCount = data.items.filter((item) => item.status === statusFilter).length;
    document.getElementById('queue-count').textContent = `${pendingCount} pendentes`;
    const navCount = document.getElementById('queue-count-nav');
    if (navCount) {
      navCount.textContent = pendingCount;
      navCount.classList.toggle('hidden', pendingCount === 0);
    }
    renderReviewQueue(data.items);
  }

  function renderReviewQueue(items) {
    const container = document.getElementById(containerId);
    if (!items.length) {
      container.innerHTML = '<div class="alert-banner alert-info"><strong>Nenhuma nota aguardando aprovacao.</strong></div>';
      return;
    }
    const directorExtraHead = role === 'director' ? '<th scope="col">Gestor</th><th scope="col">Aprovado pelo Gestor em</th>' : '';
    container.innerHTML = `<table class="table"><caption class="sr-only">Fila de notas aguardando aprovacao</caption><thead><tr>
      <th scope="col">Funcionario</th><th scope="col">Setor</th><th scope="col">Numero da nota</th><th scope="col">Valor</th><th scope="col">Emissao</th><th scope="col">Vencimento</th><th scope="col">Dias ate vencer</th>${directorExtraHead}<th scope="col">Acoes</th>
    </tr></thead><tbody>${items.map((item) => {
      const canReview = item.status === statusFilter;
      const directorExtra = role === 'director' ? `<td>${escapeHtml(item.manager?.name || '-')}</td><td>${formatDateTime(item.manager_reviewed_at)}</td>` : '';
      return `<tr>
        <td>${escapeHtml(item.created_by.name)}</td>
        <td>${escapeHtml(item.department_name || '-')}</td>
        <td>${escapeHtml(item.invoice_number)}</td>
        <td>${formatCurrency(item.amount)}</td>
        <td>${formatDate(item.issue_date)}</td>
        <td>${formatDate(item.due_date)}</td>
        <td>${daysBadge(item.due_date)}</td>
        ${directorExtra}
        <td class="table-actions">
          <button class="btn btn-ghost btn-sm" data-drawer="${item.id}">Ver</button>
          ${canReview ? `<button class="btn btn-secondary btn-sm" data-action="APPROVE" data-id="${item.id}">Aprovar</button><button class="btn btn-danger btn-sm" data-action="REJECT" data-id="${item.id}">Reprovar</button>` : statusBadge(item.status)}
        </td>
      </tr>`;
    }).join('')}</tbody></table>`;
    container.querySelectorAll('button[data-action]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (role === 'manager' && button.dataset.action === 'APPROVE') {
          let directors = [];
          try { directors = await apiFetch('/api/invoices/directors'); } catch {}
          const directorId = await pickDirectorModal(directors);
          if (!directorId) return;
          const ok = await reviewInvoice(button.dataset.id, 'APPROVE', `/api/invoices/${button.dataset.id}/${endpointPart}`, directorId);
          if (ok) await loadReviewQueue();
        } else {
          const ok = await reviewInvoice(button.dataset.id, button.dataset.action, `/api/invoices/${button.dataset.id}/${endpointPart}`);
          if (ok) await loadReviewQueue();
        }
      });
    });
  }
  await loadReviewQueue();
}

async function initReviewDetail(role) {
  const invoiceId = getInvoiceIdFromPath();
  const invoice = await apiFetch(invoiceApiPath(invoiceId));
  renderInvoiceDetail(invoice);
  if (invoice.has_attachment) loadPdfInline(invoiceId);

  const statusNeeded = role === 'manager' ? 'AGUARDANDO_GESTOR' : 'AGUARDANDO_DIRETOR';
  if (invoice.status !== statusNeeded) return;

  const panel = document.getElementById('review-panel');
  if (!panel) return;
  panel.classList.remove('hidden');

  if (role === 'manager') {
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'director-list', 'chosen-director-id');
    } catch {
      const el = document.getElementById('director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
    document.getElementById('btn-approve')?.addEventListener('click', async () => {
      const dirId = document.getElementById('chosen-director-id')?.value;
      if (!dirId) { showToast('Selecione um diretor para encaminhar a nota.', 'error'); return; }
      try {
        await apiFetch(`/api/invoices/${invoiceId}/review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'APPROVE', director_id: dirId })
        });
        showToast('Nota aprovada e encaminhada ao diretor.', 'success');
        window.location.reload();
      } catch (e) { showToast(e.message, 'error'); }
    });
  } else {
    document.getElementById('btn-approve')?.addEventListener('click', async () => {
      try {
        await apiFetch(`/api/invoices/${invoiceId}/director-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'APPROVE' })
        });
        showToast('Nota aprovada com sucesso.', 'success');
        window.location.reload();
      } catch (e) { showToast(e.message, 'error'); }
    });
  }

  const endpoint = role === 'manager' ? 'review' : 'director-review';
  document.getElementById('btn-show-reject')?.addEventListener('click', () => {
    document.getElementById('reject-section')?.classList.remove('hidden');
    document.getElementById('btn-approve')?.setAttribute('disabled', '');
    document.getElementById('btn-show-reject')?.setAttribute('disabled', '');
  });
  document.getElementById('btn-cancel-reject')?.addEventListener('click', () => {
    document.getElementById('reject-section')?.classList.add('hidden');
    document.getElementById('btn-approve')?.removeAttribute('disabled');
    document.getElementById('btn-show-reject')?.removeAttribute('disabled');
  });
  const rejectComment = document.getElementById('reject-comment');
  const confirmBtn = document.getElementById('btn-confirm-reject');
  rejectComment?.addEventListener('input', () => {
    if (confirmBtn) confirmBtn.disabled = rejectComment.value.trim().length < 10;
  });
  confirmBtn?.addEventListener('click', async () => {
    try {
      await apiFetch(`/api/invoices/${invoiceId}/${endpoint}`, {
        method: 'POST',
        body: JSON.stringify({ action: 'REJECT', comment: rejectComment.value.trim() })
      });
      showToast('Nota reprovada.', 'success');
      window.location.reload();
    } catch (e) { showToast(e.message, 'error'); }
  });
}

// ── Admin helpers ────────────────────────────────────────────────────────────

const adminRoleLabels = { ...ROLE_LABELS, ADMIN: 'Admin', FINANCE: 'Financeiro' };

let adminUsersCache = [];
let adminAuditState = { page: 1, pages: 1, filters: {} };

function adminRoleBadge(role) {
  // CONTAS_A_PAGAR -> contas-a-pagar pra casar com os tokens --role-* do CSS
  const cls = String(role).toLowerCase().replace(/_/g, '-');
  const code = {
    ADMIN: 'ADM',
    FINANCE: 'FIN',
    CONTAS_A_PAGAR: 'CAP',
    DIRECTOR: 'DIR',
    MANAGER: 'GES',
    EMPLOYEE: 'FUN',
  }[role] || String(role).slice(0, 3).toUpperCase();
  return `<span class="role-chip role-${cls}"><span class="role-chip-code" aria-hidden="true">${escapeHtml(code)}</span><span>${escapeHtml(adminRoleLabels[role] || role)}</span></span>`;
}

function adminAvatar(name) {
  if (!name) return '<span class="avatar">?</span>';
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts[0]?.[0] || '';
  const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
  return `<span class="avatar">${escapeHtml((first + last).toUpperCase())}</span>`;
}

function adminUserStatus(user) {
  if (!user.is_active) return '<span class="status-badge user-status-inactive">Inativo</span>';
  if (user.blocked_until && new Date(user.blocked_until) > new Date()) {
    return '<span class="status-badge user-status-blocked">Bloqueado</span>';
  }
  return '<span class="status-badge user-status-active">Ativo</span>';
}

async function adminLoadManagers(selectId, selectedId = '') {
  const select = document.getElementById(selectId);
  if (!select) return;
  const managers = await apiFetch('/api/admin/managers');
  select.innerHTML = '<option value="">Sem gestor</option>';
  managers.forEach((manager) => {
    const option = document.createElement('option');
    option.value = manager.id;
    option.textContent = manager.name;
    option.selected = manager.id === selectedId;
    select.appendChild(option);
  });
}

async function adminLoadDepartments(selectId, selectedId = '') {
  const select = document.getElementById(selectId);
  if (!select) return;
  try {
    const depts = await apiFetch('/api/admin/departments');
    select.innerHTML = '<option value="">Sem departamento</option>';
    depts.forEach((dept) => {
      const option = document.createElement('option');
      option.value = dept.id;
      option.textContent = dept.name;
      option.selected = dept.id === selectedId;
      select.appendChild(option);
    });
  } catch {
    select.innerHTML = '<option value="">Erro ao carregar departamentos</option>';
  }
}

function adminToggleManagerField(roleId, fieldId) {
  const role = document.getElementById(roleId)?.value;
  document.getElementById(fieldId)?.classList.toggle('hidden', role !== 'EMPLOYEE');
}

async function initAdminUsers() {
  document.getElementById('admin-edit-cancel')?.addEventListener('click', () => {
    document.getElementById('admin-edit-modal').classList.add('hidden');
  });
  document.getElementById('admin-reset-cancel')?.addEventListener('click', () => {
    document.getElementById('admin-reset-modal').classList.add('hidden');
  });
  document.getElementById('admin-edit-role')?.addEventListener('change', () => {
    adminToggleManagerField('admin-edit-role', 'admin-edit-manager-field');
  });
  document.getElementById('admin-edit-form')?.addEventListener('submit', saveAdminEdit);
  document.getElementById('admin-reset-form')?.addEventListener('submit', resetAdminPassword);
  // Filtros instantaneos
  document.getElementById('admin-users-search')?.addEventListener('input', applyAdminUsersFilter);
  document.getElementById('admin-users-role-filter')?.addEventListener('change', applyAdminUsersFilter);
  document.getElementById('admin-users-status-filter')?.addEventListener('change', applyAdminUsersFilter);
  await adminLoadManagers('admin-edit-manager');
  await loadAdminUsers();
}

async function loadAdminUsers() {
  try {
    adminUsersCache = await apiFetch('/api/admin/users');
    applyAdminUsersFilter();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function applyAdminUsersFilter() {
  const term = (document.getElementById('admin-users-search')?.value || '').trim().toLowerCase();
  const roleFilter = document.getElementById('admin-users-role-filter')?.value || '';
  const statusFilter = document.getElementById('admin-users-status-filter')?.value || '';

  const filtered = (adminUsersCache || []).filter((user) => {
    // Busca textual livre — bate em qualquer um destes campos
    if (term) {
      const haystack = [
        user.name,
        user.email,
        user.role,
        user.department_name,
        user.id,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(term)) return false;
    }
    // Filtro de perfil
    if (roleFilter && user.role !== roleFilter) return false;
    // Filtro de status
    if (statusFilter) {
      const blocked = user.blocked_until && new Date(user.blocked_until) > new Date();
      if (statusFilter === 'active' && (!user.is_active || blocked)) return false;
      if (statusFilter === 'inactive' && user.is_active) return false;
      if (statusFilter === 'blocked' && !blocked) return false;
    }
    return true;
  });

  const countEl = document.getElementById('admin-users-count');
  if (countEl) {
    const total = (adminUsersCache || []).length;
    countEl.textContent = filtered.length === total
      ? `${total} usuario${total === 1 ? '' : 's'}`
      : `${filtered.length} de ${total}`;
  }

  renderAdminUsersTable(filtered);
}

function renderAdminUsersTable(users) {
  const tbody = document.getElementById('admin-users-tbody');
  if (!tbody) return;
  if (!users.length) {
    const total = (adminUsersCache || []).length;
    const msg = total === 0
      ? 'Nenhum usuario cadastrado.'
      : 'Nenhum usuario corresponde aos filtros aplicados.';
    tbody.innerHTML = `<tr><td colspan="7" class="text-muted">${msg}</td></tr>`;
    return;
  }
  const me = Auth.getUser();
  tbody.innerHTML = users.map((user) => {
    const blocked = user.blocked_until && new Date(user.blocked_until) > new Date();
    const isAdmin = user.role === 'ADMIN';
    const isSelf = user.id === me?.id;
    const isAnon = Boolean(user.is_anonymized);
    // Usuario anonimizado e estado final: nenhuma acao de identidade
    // permitida. So sobra abrir o registro pra historico.
    const toggleBtn = (!isAdmin && !isSelf && !isAnon)
      ? `<button class="btn ${user.is_active ? 'btn-ghost' : 'btn-secondary'} btn-sm" data-action="toggle" data-id="${user.id}" data-active="${user.is_active}" title="${user.is_active ? 'Desativar' : 'Ativar'}" aria-label="${user.is_active ? 'Desativar' : 'Ativar'}"><span class="icon icon-${user.is_active ? 'eye-off' : 'eye'} ic-16"></span></button>`
      : '';
    const unlockBtn = (blocked && !isAdmin && !isAnon)
      ? `<button class="btn btn-ghost btn-sm" data-action="unlock" data-id="${user.id}" title="Desbloquear" aria-label="Desbloquear"><span class="icon icon-circle-check ic-16"></span></button>`
      : '';
    const anonymizeBtn = (!isAdmin && !isSelf && !user.is_active && !isAnon)
      ? `<button class="btn btn-ghost btn-sm btn-danger-text" data-action="anonymize" data-id="${user.id}" data-name="${escapeHtml(user.name)}" title="Encerrar conta" aria-label="Encerrar conta"><span class="icon icon-archive ic-16"></span></button>`
      : '';
    const editBtns = isAnon
      ? '<span class="text-muted text-xs" title="Conta encerrada — registro preservado para auditoria fiscal">Conta encerrada</span>'
      : `
        <a class="btn btn-ghost btn-sm" href="/admin/users/${user.id}/edit" title="Editar completo" aria-label="Editar completo"><span class="icon icon-external-link ic-16"></span></a>
        <button class="btn btn-ghost btn-sm" data-action="quick-edit" data-id="${user.id}" title="Editar rapido" aria-label="Editar rapido"><span class="icon icon-pencil ic-16"></span></button>
        <button class="btn btn-ghost btn-sm" data-action="reset" data-id="${user.id}" title="Redefinir senha" aria-label="Redefinir senha"><span class="icon icon-lock ic-16"></span></button>
      `;
    const rowCls = isAdmin ? ' class="row-admin"' : (isAnon ? ' class="row-anonymized"' : '');
    const nameCell = `<div class="user-name-cell">${adminAvatar(user.name)}<div><strong>${escapeHtml(user.name)}</strong>${isSelf ? ' <span class="badge-self">voce</span>' : ''}${isAnon ? ' <span class="badge-anon">encerrada</span>' : ''}</div></div>`;
    return `<tr${rowCls} data-user-id="${user.id}" data-anonymized="${isAnon}">
      <td>${nameCell}</td>
      <td>${escapeHtml(user.email)}</td>
      <td>${adminRoleBadge(user.role)}</td>
      <td>${escapeHtml(user.department_name || '-')}</td>
      <td>${adminUserStatus(user)}</td>
      <td>${formatDateTime(user.last_login)}</td>
      <td class="table-actions">
        ${editBtns}${unlockBtn}${toggleBtn}${anonymizeBtn}
      </td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', () => handleAdminUserAction(button));
  });
}

async function handleAdminUserAction(button) {
  const { action, id } = button.dataset;
  if (action === 'quick-edit') await openAdminEditModal(id);
  if (action === 'reset') openAdminResetModal(id);
  if (action === 'unlock') await unlockAdminUser(id);
  if (action === 'toggle') await toggleAdminUserActive(id, button.dataset.active === 'true');
  if (action === 'anonymize') await anonymizeAdminUser(id, button.dataset.name);
}

async function anonymizeAdminUser(userId, userName) {
  const msg =
    `Encerrar definitivamente a conta de "${userName}"?\n\n` +
    `Nome, email e senha serao substituidos por placeholders. ` +
    `O usuario nao podera mais logar.\n\n` +
    `O historico de aprovacoes e preservado por exigencia fiscal (5 anos).\n\n` +
    `Esta acao nao pode ser desfeita.`;
  if (!(await confirmAction(msg))) return;
  try {
    const resp = await apiFetch(`/api/admin/users/${userId}/anonymize`, { method: 'POST' });
    showToast(resp.message || 'Usuario anonimizado.', 'success');
    await loadAdminUsers();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function openAdminEditModal(userId) {
  try {
    const user = await apiFetch(`/api/admin/users/${userId}`);
    document.getElementById('admin-edit-user-id').value = user.id;
    document.getElementById('admin-edit-name').value = user.name;
    document.getElementById('admin-edit-role').value = user.role;
    document.getElementById('admin-edit-must-change').checked = Boolean(user.must_change_password);
    document.getElementById('admin-edit-submit-directly').checked = Boolean(user.submit_directly_to_director);
    await adminLoadDepartments('admin-edit-dept-id', user.department_id || '');
    await adminLoadManagers('admin-edit-manager', user.manager_id || '');
    adminToggleManagerField('admin-edit-role', 'admin-edit-manager-field');
    document.getElementById('admin-edit-modal').classList.remove('hidden');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveAdminEdit(event) {
  event.preventDefault();
  const userId = document.getElementById('admin-edit-user-id').value;
  const role = document.getElementById('admin-edit-role').value;
  const payload = {
    name: document.getElementById('admin-edit-name').value.trim(),
    department_id: document.getElementById('admin-edit-dept-id').value || null,
    submit_directly_to_director: document.getElementById('admin-edit-submit-directly').checked,
    role,
    manager_id: role === 'EMPLOYEE' ? document.getElementById('admin-edit-manager').value : '',
    must_change_password: document.getElementById('admin-edit-must-change').checked
  };
  try {
    await apiFetch(`/api/admin/users/${userId}`, { method: 'PUT', body: JSON.stringify(payload) });
    document.getElementById('admin-edit-modal').classList.add('hidden');
    showToast('Usuario atualizado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function openAdminResetModal(userId) {
  const user = adminUsersCache.find((item) => item.id === userId);
  document.getElementById('admin-reset-user-id').value = userId;
  document.getElementById('admin-reset-password').value = '';
  document.getElementById('admin-reset-user-label').textContent = user ? user.email : '';
  document.getElementById('admin-reset-modal').classList.remove('hidden');
}

async function resetAdminPassword(event) {
  event.preventDefault();
  const userId = document.getElementById('admin-reset-user-id').value;
  const newPassword = document.getElementById('admin-reset-password').value;
  try {
    await apiFetch(`/api/admin/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword })
    });
    document.getElementById('admin-reset-modal').classList.add('hidden');
    showToast('Senha redefinida.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function unlockAdminUser(userId) {
  try {
    await apiFetch(`/api/admin/users/${userId}/unlock`, { method: 'POST' });
    showToast('Usuario desbloqueado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function toggleAdminUserActive(userId, currentActive) {
  if (!(await confirmAction(currentActive ? 'Desativar este usuario?' : 'Ativar este usuario?'))) return;
  try {
    await apiFetch(`/api/admin/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: !currentActive })
    });
    showToast(currentActive ? 'Usuario desativado.' : 'Usuario ativado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function initAdminUserForm() {
  const page = document.getElementById('admin-user-form-page');
  const mode = page.dataset.mode;
  const userId = page.dataset.userId;
  document.getElementById('admin-user-role')?.addEventListener('change', () => {
    adminToggleManagerField('admin-user-role', 'admin-manager-field');
  });
  await adminLoadManagers('admin-user-manager');
  await adminLoadDepartments('admin-user-dept-id');
  if (mode === 'edit') {
    document.getElementById('admin-user-email').disabled = true;
    document.getElementById('admin-password-field').classList.add('hidden');
    await loadAdminUserFormData(userId);
  }
  adminToggleManagerField('admin-user-role', 'admin-manager-field');
  document.getElementById('admin-user-form')?.addEventListener('submit', saveAdminUserForm);
}

async function loadAdminUserFormData(userId) {
  try {
    const user = await apiFetch(`/api/admin/users/${userId}`);
    document.getElementById('admin-user-name').value = user.name;
    document.getElementById('admin-user-email').value = user.email;
    document.getElementById('admin-user-role').value = user.role;
    document.getElementById('admin-user-must-change').checked = Boolean(user.must_change_password);
    document.getElementById('admin-user-submit-directly').checked = Boolean(user.submit_directly_to_director);
    await adminLoadDepartments('admin-user-dept-id', user.department_id || '');
    await adminLoadManagers('admin-user-manager', user.manager_id || '');
    adminToggleManagerField('admin-user-role', 'admin-manager-field');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveAdminUserForm(event) {
  event.preventDefault();
  const page = document.getElementById('admin-user-form-page');
  const mode = page.dataset.mode;
  const userId = page.dataset.userId;
  const role = document.getElementById('admin-user-role').value;
  const departmentId = document.getElementById('admin-user-dept-id').value || null;
  const submitDirectly = document.getElementById('admin-user-submit-directly').checked;
  const managerId = document.getElementById('admin-user-manager').value || '';

  // Validacoes client-side espelhando as do backend pra dar feedback imediato
  if (role !== 'ADMIN' && !departmentId) {
    showToast('Selecione um setor para este perfil.', 'error');
    return;
  }
  if (role === 'EMPLOYEE' && !managerId && !submitDirectly) {
    showToast('Funcionario precisa de gestor ou da opcao "envia direto ao diretor".', 'error');
    return;
  }

  const payload = {
    name: document.getElementById('admin-user-name').value.trim(),
    role,
    department_id: departmentId,
    submit_directly_to_director: submitDirectly,
    manager_id: role === 'EMPLOYEE' ? managerId : '',
    must_change_password: document.getElementById('admin-user-must-change').checked
  };
  if (mode === 'create') {
    payload.email = document.getElementById('admin-user-email').value.trim();
    payload.password = document.getElementById('admin-user-password').value;
    if (payload.password.length < 8) {
      showToast('Senha deve ter no minimo 8 caracteres.', 'error');
      return;
    }
  }
  try {
    const url = mode === 'create' ? '/api/admin/users' : `/api/admin/users/${userId}`;
    const method = mode === 'create' ? 'POST' : 'PUT';
    await apiFetch(url, { method, body: JSON.stringify(payload) });
    showToast(mode === 'create' ? 'Usuario criado com sucesso!' : 'Alteracoes salvas.', 'success');
    setTimeout(() => { window.location.href = '/admin/users'; }, 1500);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function initAdminAuditLogs() {
  await loadAdminAuditUsers();
  document.getElementById('admin-audit-filter-form')?.addEventListener('submit', (event) => {
    event.preventDefault();
    adminAuditState.page = 1;
    adminAuditState.filters = readAdminAuditFilters();
    loadAdminAuditLogs();
  });
  document.getElementById('admin-audit-clear')?.addEventListener('click', () => {
    document.getElementById('admin-audit-filter-form').reset();
    adminAuditState.page = 1;
    adminAuditState.filters = {};
    loadAdminAuditLogs();
  });
  document.getElementById('admin-audit-prev')?.addEventListener('click', () => {
    if (adminAuditState.page > 1) {
      adminAuditState.page -= 1;
      loadAdminAuditLogs();
    }
  });
  document.getElementById('admin-audit-next')?.addEventListener('click', () => {
    if (adminAuditState.page < adminAuditState.pages) {
      adminAuditState.page += 1;
      loadAdminAuditLogs();
    }
  });
  await loadAdminAuditLogs();
}

async function loadAdminAuditUsers() {
  const select = document.getElementById('admin-audit-user');
  if (!select) return;
  try {
    const users = await apiFetch('/api/admin/users');
    users.forEach((user) => {
      const option = document.createElement('option');
      option.value = user.id;
      option.textContent = `${user.name} (${user.email})`;
      select.appendChild(option);
    });
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function readAdminAuditFilters() {
  return {
    action: document.getElementById('admin-audit-action').value.trim(),
    user_id: document.getElementById('admin-audit-user').value,
    success: document.getElementById('admin-audit-success').value
  };
}

async function loadAdminAuditLogs() {
  const params = new URLSearchParams({
    page: adminAuditState.page,
    per_page: 50,
    ...adminAuditState.filters
  });
  [...params.entries()].forEach(([key, value]) => {
    if (!value) params.delete(key);
  });
  try {
    const data = await apiFetch(`/api/admin/audit-logs?${params.toString()}`);
    adminAuditState.pages = data.pages || 1;
    renderAdminAuditLogs(data);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderAdminAuditLogs(data) {
  const tbody = document.getElementById('admin-audit-tbody');
  if (!tbody) return;
  document.getElementById('admin-audit-total').textContent = `${data.total} registros`;
  document.getElementById('admin-audit-page').textContent = `Pagina ${data.page} de ${adminAuditState.pages}`;
  document.getElementById('admin-audit-prev').disabled = data.page <= 1;
  document.getElementById('admin-audit-next').disabled = data.page >= adminAuditState.pages;
  if (!data.items.length) {
    tbody.innerHTML = '<tr><td colspan="6">Nenhum log encontrado.</td></tr>';
    return;
  }
  tbody.innerHTML = data.items.map((log) => `
    <tr class="audit-row" data-log-id="${log.id}">
      <td>${formatDateTime(log.timestamp)}</td>
      <td>${escapeHtml(log.user_name || 'Sistema')}<div class="table-subtext">${escapeHtml(log.user_email || '')}</div></td>
      <td><span class="audit-action-badge">${escapeHtml(log.action)}</span></td>
      <td>${escapeHtml(log.resource_type || '-')}${log.resource_id ? `<div class="table-subtext">${escapeHtml(log.resource_id)}</div>` : ''}</td>
      <td>${escapeHtml(log.ip_address || '-')}</td>
      <td>${log.success ? '<span class="status-badge user-status-active">Sucesso</span>' : '<span class="status-badge user-status-inactive">Falha</span>'}</td>
    </tr>
    <tr class="audit-detail-row hidden" data-detail-for="${log.id}">
      <td colspan="6">${escapeHtml(log.detail || 'Sem detalhes.')}</td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.audit-row').forEach((row) => {
    row.addEventListener('click', () => {
      tbody.querySelector(`[data-detail-for="${row.dataset.logId}"]`)?.classList.toggle('hidden');
    });
  });
}

function rejectReasonModal() {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h2>Reprovar nota</h2>
        <p class="text-muted">Informe o motivo da reprovacao.</p>
        <textarea class="form-input review-modal-field" id="reject-reason" minlength="10" maxlength="1000" placeholder="Motivo com no minimo 10 caracteres"></textarea>
        <div class="modal-actions">
          <button class="btn btn-ghost" data-action="cancel">Cancelar</button>
          <button class="btn btn-danger" data-action="confirm" disabled>Reprovar</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    const textarea = backdrop.querySelector('#reject-reason');
    const confirm = backdrop.querySelector('[data-action="confirm"]');
    textarea.addEventListener('input', () => { confirm.disabled = textarea.value.trim().length < 10; });
    backdrop.addEventListener('click', (event) => {
      const action = event.target.dataset.action;
      if (!action) return;
      const value = textarea.value.trim();
      backdrop.remove();
      resolve(action === 'confirm' && value.length >= 10 ? value : null);
    });
    textarea.focus();
  });
}

// ── Invoice Drawer ────────────────────────────────────────────────────────────
// Drawer lateral — abre nota com PDF + ações sem mudar de página

let _drawerEl = null;
let _drawerBackdrop = null;

function _ensureDrawer() {
  if (_drawerEl) return;

  _drawerBackdrop = document.createElement('div');
  _drawerBackdrop.className = 'drawer-backdrop';
  _drawerBackdrop.addEventListener('click', closeDrawer);
  document.body.appendChild(_drawerBackdrop);

  _drawerEl = document.createElement('div');
  _drawerEl.className = 'invoice-drawer';
  _drawerEl.innerHTML = `
    <div class="drawer-header">
      <button class="btn btn-ghost btn-sm" id="drawer-close">&#8592; Fechar</button>
      <div class="drawer-header-info">
        <h2 id="drawer-title">Carregando...</h2>
        <p class="text-muted" id="drawer-subtitle"></p>
      </div>
      <div class="drawer-header-right">
        <div id="drawer-status"></div>
        <a id="drawer-open-page" class="btn btn-ghost btn-sm" style="display:none">Abrir pagina</a>
      </div>
    </div>
    <div class="drawer-body">
      <div id="drawer-rejection-box" class="alert-banner alert-error hidden"></div>
      <div id="drawer-review-panel" class="review-panel card hidden"></div>
      <div id="drawer-actions" class="action-row"></div>
      <div class="detail-layout">
        <div class="detail-left">
          <div class="detail-grid" id="drawer-grid"></div>
          <div class="section-header"><h2>Timeline</h2></div>
          <div class="timeline" id="drawer-timeline"></div>

          <div class="section-header">
            <h2>Comentarios <span id="drawer-comments-count" class="text-muted text-xs"></span></h2>
          </div>
          <div id="drawer-comments-thread" class="comments-thread"></div>
          <form id="drawer-comments-form" class="comments-form" aria-label="Adicionar comentario">
            <textarea id="drawer-comments-input" rows="2" maxlength="2000" placeholder="Adicione um comentario..." aria-describedby="drawer-comments-help"></textarea>
            <div class="comments-form-footer">
              <small id="drawer-comments-help" class="text-muted text-xs">Maximo 2000 caracteres. Comentarios sao permanentes.</small>
              <button type="submit" id="drawer-comments-submit" class="btn btn-primary btn-sm" disabled>Comentar</button>
            </div>
          </form>
        </div>
        <div class="detail-right" id="drawer-pdf-panel" style="display:none">
          <div class="pdf-panel-header">
            <span>Documento PDF</span>
            <a id="drawer-pdf-link" class="btn btn-ghost btn-sm" target="_blank">Abrir em nova aba</a>
          </div>
          <iframe id="drawer-pdf-iframe" class="pdf-iframe" title="PDF da nota"></iframe>
        </div>
      </div>
    </div>`;
  document.body.appendChild(_drawerEl);
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
}

function closeDrawer() {
  _drawerEl?.classList.remove('open');
  _drawerBackdrop?.classList.remove('open');
}

async function openInvoiceDrawer(invoiceId) {
  _ensureDrawer();

  // Reset UI
  document.getElementById('drawer-title').textContent = 'Carregando...';
  document.getElementById('drawer-subtitle').textContent = '';
  document.getElementById('drawer-status').innerHTML = '';
  document.getElementById('drawer-grid').innerHTML = '';
  document.getElementById('drawer-timeline').innerHTML = '';
  document.getElementById('drawer-actions').innerHTML = '';
  document.getElementById('drawer-rejection-box').classList.add('hidden');
  document.getElementById('drawer-review-panel').classList.add('hidden');
  document.getElementById('drawer-pdf-panel').style.display = 'none';
  document.getElementById('drawer-pdf-iframe').src = '';
  // Reset da thread de comentarios — evita mostrar comentarios da nota
  // anterior enquanto a nova carrega.
  const _dct = document.getElementById('drawer-comments-thread');
  if (_dct) _dct.innerHTML = '';
  const _dcc = document.getElementById('drawer-comments-count');
  if (_dcc) _dcc.textContent = '';
  const _dci = document.getElementById('drawer-comments-input');
  if (_dci) _dci.value = '';
  // Limpa o flag de bound pra permitir re-bind no novo invoiceId
  const _dcf = document.getElementById('drawer-comments-form');
  if (_dcf) delete _dcf.dataset.commentsBound;

  const pageLink = document.getElementById('drawer-open-page');
  pageLink.style.display = 'none';

  _drawerBackdrop.classList.add('open');
  _drawerEl.classList.add('open');

  try {
    const invoice = await apiFetch(`/api/invoices/${invoiceId}`);
    _renderDrawerContent(invoice);
    if (invoice.has_attachment) _loadDrawerPdf(invoiceId);
    // Carrega thread de comentarios direto no drawer (sem precisar abrir
    // a pagina completa de detail). Pedido do usuario.
    if (window.setupDrawerComments) {
      window.setupDrawerComments(invoiceId);
    }
  } catch (e) {
    document.getElementById('drawer-title').textContent = 'Erro ao carregar';
    document.getElementById('drawer-grid').innerHTML = `<p class="text-muted">${escapeHtml(e.message)}</p>`;
  }
}

function _renderDrawerContent(invoice) {
  const user = Auth.getUser();

  document.getElementById('drawer-title').textContent = `Nota ${invoice.invoice_number}`;
  document.getElementById('drawer-subtitle').textContent =
    `${escapeHtml(invoice.created_by.name)} · ${formatDateTime(invoice.created_at)}`;
  renderInvoiceAlerts(invoice, 'drawer-grid');
  renderAttachmentsBlock(invoice, '#drawer-pdf-panel');
  // Status + indicador de comentarios. Pedido do usuario: ver na hora se
  // a nota tem conversa antes de abrir.
  const _cc = invoice.comments_count || 0;
  const _commentsChip = _cc > 0
    ? ` <span class="status-badge" style="background:#fff3cd;color:#856404" title="${_cc} comentario${_cc === 1 ? '' : 's'} nesta nota">💬 ${_cc}</span>`
    : '';
  document.getElementById('drawer-status').innerHTML = statusBadge(invoice.status) + _commentsChip;

  // Link para página completa (edição, etc.)
  const pageLink = document.getElementById('drawer-open-page');
  pageLink.href = `/invoices/${invoice.id}`;
  pageLink.style.display = '';

  const docLabel = invoice.supplier_document_type || 'CPF/CNPJ';
  const docFmt = invoice.supplier_document ? formatDocument(invoice.supplier_document) : '-';
  document.getElementById('drawer-grid').innerHTML = [
    ['Valor',          formatCurrency(invoice.amount)],
    ['Emissao',        formatDate(invoice.issue_date)],
    ['Vencimento',     formatDate(invoice.due_date)],
    ['Setor',          invoice.department_name || '-'],
    [docLabel,         docFmt],
    ['Fornecedor',     invoice.supplier_name || '-'],
    ['Descricao',      invoice.description],
    ['Dados bancarios', invoice.bank_details || '-'],
  ].map(([l, v]) => `<div class="detail-item"><span>${l}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('');

  const rejection = [...invoice.history].reverse().find((h) => h.action.startsWith('REJECTED'));
  const rejBox = document.getElementById('drawer-rejection-box');
  if (rejection) {
    rejBox.innerHTML = `<strong>Motivo da reprovacao:</strong> ${escapeHtml(rejection.comment || '-')}`;
    rejBox.classList.remove('hidden');
  }

  const icons  = { CREATED: '+', SUBMITTED: '>', APPROVED_MANAGER: '✓', REJECTED_MANAGER: '✗', APPROVED_DIRECTOR: '✓', REJECTED_DIRECTOR: '✗', MARKED_PAID: '$', PRINTED: '🖨' };
  const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Cancelada', APPROVED_MANAGER: 'Aprovada gestor', REJECTED_MANAGER: 'Reprovada gestor', APPROVED_DIRECTOR: 'Aprovada diretor', REJECTED_DIRECTOR: 'Reprovada diretor', MARKED_PAID: 'Lancada', PRINTED: 'Comprovante impresso', TRANSFERRED_DIRECTOR: 'Repasse de diretor' };
  document.getElementById('drawer-timeline').innerHTML = invoice.history.map((h) => `
    <div class="timeline-item">
      <div class="timeline-icon">${icons[h.action] || '·'}</div>
      <div><strong>${labels[h.action] || h.action}</strong>
        <div class="timeline-meta">${escapeHtml(h.user.name)} · ${formatDateTime(h.timestamp)}</div>
        ${h.comment ? `<p>${escapeHtml(h.comment)}</p>` : ''}
      </div>
    </div>`).join('');

  _renderDrawerActions(invoice, user);
}

async function _renderDrawerActions(invoice, user) {
  const role = user?.role;

  // Gestor revisando
  if (role === 'MANAGER' && invoice.status === 'AGUARDANDO_GESTOR') {
    return _renderDrawerManagerReview(invoice);
  }
  // Diretor revisando
  if (role === 'DIRECTOR' && invoice.status === 'AGUARDANDO_DIRETOR') {
    return _renderDrawerDirectorReview(invoice);
  }
  // Financeiro — imprimir comprovante (APROVADO = 1a impressao | PAGO = reimpressao)
  if (role === 'FINANCE' && (invoice.status === 'APROVADO' || invoice.status === 'PAGO')) {
    return _renderDrawerFinance(invoice);
  }

  // Funcionário / criador da nota
  const actionsEl = document.getElementById('drawer-actions');
  const isDirect = Boolean(user?.submit_directly_to_director);
  const buttons = [];

  if (invoice.can_cancel) {
    buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
  }
  if (invoice.status === 'RASCUNHO') {
    buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
    buttons.push(isDirect
      ? '<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>'
      : '<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }
  if (invoice.status.startsWith('REPROVADO')) {
    buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }

  let dirHtml = '';
  if (invoice.status === 'RASCUNHO' && isDirect) {
    dirHtml = `<div class="form-group" style="margin-bottom:1rem">
      <label class="form-label">Enviar para o diretor:</label>
      <div id="drawer-dir-list" class="director-list"><p class="text-muted">Carregando...</p></div>
      <input type="hidden" id="drawer-dir-chosen">
    </div>`;
  }
  actionsEl.innerHTML = dirHtml + buttons.join('');

  if (invoice.status === 'RASCUNHO' && isDirect) {
    try {
      const dirs = await apiFetch('/api/invoices/directors');
      renderDirectorList(dirs, 'drawer-dir-list', 'drawer-dir-chosen');
    } catch {
      const el = document.getElementById('drawer-dir-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }

  actionsEl.querySelectorAll('button[data-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        if (btn.dataset.action === 'submit') {
          const updated = await submitInvoiceWithDuplicateCheck(invoice.id);
          if (!updated) return;
          showToast('Nota enviada para o gestor.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'submit-direct') {
          const dirId = document.getElementById('drawer-dir-chosen')?.value;
          if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
          const updated = await submitInvoiceWithDuplicateCheck(invoice.id, dirId);
          if (!updated) return;
          showToast('Nota enviada para o diretor.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'cancel') {
          if (!(await confirmAction('Cancelar esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}/cancel`, { method: 'POST' });
          showToast('Nota cancelada.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'delete') {
          if (!(await confirmAction('Excluir esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}`, { method: 'DELETE' });
          showToast('Nota excluida.', 'success');
          _refreshAfterAction();
        }
      } catch (e) { showToast(e.message, 'error'); }
    });
  });
}

async function _renderDrawerManagerReview(invoice) {
  const panel = document.getElementById('drawer-review-panel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <h3>Revisar nota</h3>
    <div style="margin-bottom:1rem">
      <label class="form-label">Encaminhar para o diretor:</label>
      <div id="drawer-mgr-dir-list" class="director-list"><p class="text-muted">Carregando...</p></div>
      <input type="hidden" id="drawer-mgr-dir-chosen">
    </div>
    <div class="review-actions">
      <button class="btn btn-primary" id="drawer-mgr-approve">Aprovar e encaminhar</button>
      <button class="btn btn-ghost" id="drawer-mgr-show-reject">Reprovar</button>
    </div>
    <div id="drawer-mgr-reject-sec" class="hidden" style="margin-top:1rem">
      <label class="form-label">Motivo da reprovacao (obrigatorio)</label>
      <textarea id="drawer-mgr-reject-txt" class="form-input" rows="3" maxlength="500" placeholder="Minimo 10 caracteres..."></textarea>
      <div class="review-actions" style="margin-top:.5rem">
        <button class="btn btn-danger" id="drawer-mgr-confirm-reject" disabled>Confirmar reprovacao</button>
        <button class="btn btn-ghost" id="drawer-mgr-cancel-reject">Cancelar</button>
      </div>
    </div>`;

  try {
    const dirs = await apiFetch('/api/invoices/directors');
    renderDirectorList(dirs, 'drawer-mgr-dir-list', 'drawer-mgr-dir-chosen');
  } catch {
    document.getElementById('drawer-mgr-dir-list').innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
  }

  document.getElementById('drawer-mgr-approve').addEventListener('click', async () => {
    const dirId = document.getElementById('drawer-mgr-dir-chosen')?.value;
    if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
    try {
      await apiFetch(`/api/invoices/${invoice.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'APPROVE', director_id: dirId })
      });
      showToast('Nota aprovada e encaminhada ao diretor.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });

  _wireDrawerReject('drawer-mgr-show-reject', 'drawer-mgr-reject-sec', 'drawer-mgr-cancel-reject',
    'drawer-mgr-reject-txt', 'drawer-mgr-confirm-reject', async (comment) => {
      await apiFetch(`/api/invoices/${invoice.id}/review`, {
        method: 'POST', body: JSON.stringify({ action: 'REJECT', comment })
      });
    });
}

function _renderDrawerDirectorReview(invoice) {
  const panel = document.getElementById('drawer-review-panel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <h3>Decisao do Diretor</h3>
    <div class="review-actions">
      <button class="btn btn-primary" id="drawer-dir-approve">Aprovar nota</button>
      <button class="btn btn-ghost" id="drawer-dir-show-reject">Reprovar</button>
      <button class="btn btn-ghost" id="drawer-dir-show-transfer">Repassar a outro diretor</button>
    </div>
    <div id="drawer-dir-reject-sec" class="hidden" style="margin-top:1rem">
      <label class="form-label">Motivo da reprovacao (obrigatorio)</label>
      <textarea id="drawer-dir-reject-txt" class="form-input" rows="3" maxlength="500" placeholder="Minimo 10 caracteres..."></textarea>
      <div class="review-actions" style="margin-top:.5rem">
        <button class="btn btn-danger" id="drawer-dir-confirm-reject" disabled>Confirmar reprovacao</button>
        <button class="btn btn-ghost" id="drawer-dir-cancel-reject">Cancelar</button>
      </div>
    </div>
    <div id="drawer-dir-transfer-sec" class="hidden" style="margin-top:1rem">
      <label class="form-label">Repassar para outro diretor</label>
      <p class="text-muted text-xs">A nota muda de mao mantendo o status aguardando diretor.</p>
      <div id="drawer-dir-transfer-list" class="director-list"><p class="text-muted">Carregando diretores...</p></div>
      <input type="hidden" id="drawer-dir-transfer-target">
      <label class="form-label" style="margin-top:.75rem">Motivo do repasse (minimo 10 caracteres)</label>
      <textarea id="drawer-dir-transfer-txt" class="form-input" rows="3" maxlength="500" placeholder="Ex: nota e de outro setor / conflito de interesse..."></textarea>
      <div class="review-actions" style="margin-top:.5rem">
        <button class="btn btn-primary" id="drawer-dir-confirm-transfer" disabled>Confirmar repasse</button>
        <button class="btn btn-ghost" id="drawer-dir-cancel-transfer">Cancelar</button>
      </div>
    </div>`;

  document.getElementById('drawer-dir-approve').addEventListener('click', async () => {
    try {
      await apiFetch(`/api/invoices/${invoice.id}/director-review`, {
        method: 'POST', body: JSON.stringify({ action: 'APPROVE' })
      });
      showToast('Nota aprovada.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });

  _wireDrawerReject('drawer-dir-show-reject', 'drawer-dir-reject-sec', 'drawer-dir-cancel-reject',
    'drawer-dir-reject-txt', 'drawer-dir-confirm-reject', async (comment) => {
      await apiFetch(`/api/invoices/${invoice.id}/director-review`, {
        method: 'POST', body: JSON.stringify({ action: 'REJECT', comment })
      });
    });

  // Repasse — carrega lista de outros diretores e habilita botao quando
  // motivo for valido e um diretor for selecionado
  document.getElementById('drawer-dir-show-transfer').addEventListener('click', async () => {
    document.getElementById('drawer-dir-transfer-sec').classList.remove('hidden');
    try {
      const directors = await apiFetch('/api/invoices/directors');
      const me = Auth.getUser();
      const others = directors.filter((d) => d.id !== me?.id && d.is_active && !d.unavailable_for_notes);
      renderDirectorList(others, 'drawer-dir-transfer-list', 'drawer-dir-transfer-target');
    } catch (e) {
      document.getElementById('drawer-dir-transfer-list').innerHTML =
        '<p class="text-muted">Nao foi possivel carregar a lista. Tente novamente.</p>';
    }
    const txt = document.getElementById('drawer-dir-transfer-txt');
    const btn = document.getElementById('drawer-dir-confirm-transfer');
    const targetField = document.getElementById('drawer-dir-transfer-target');
    function updateBtn() {
      btn.disabled = !(txt.value.trim().length >= 10 && targetField.value);
    }
    txt.addEventListener('input', updateBtn);
    targetField.addEventListener('change', updateBtn);
    // renderDirectorList nao dispara change em hidden — observa cliques no list
    document.getElementById('drawer-dir-transfer-list').addEventListener('click', () => setTimeout(updateBtn, 0));
  });
  document.getElementById('drawer-dir-cancel-transfer').addEventListener('click', () => {
    document.getElementById('drawer-dir-transfer-sec').classList.add('hidden');
  });
  document.getElementById('drawer-dir-confirm-transfer').addEventListener('click', async () => {
    const newId = document.getElementById('drawer-dir-transfer-target').value;
    const comment = document.getElementById('drawer-dir-transfer-txt').value.trim();
    try {
      await apiFetch(`/api/invoices/${invoice.id}/transfer-director`, {
        method: 'POST',
        body: JSON.stringify({ new_director_id: newId, comment }),
      });
      showToast('Nota repassada com sucesso.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });
}

function _renderDrawerFinance(invoice) {
  const actionsEl = document.getElementById('drawer-actions');
  const printedEntry = invoice.history.slice().reverse().find((h) => h.action === 'PRINTED');
  const lastPrint = printedEntry
    ? `<p class="receipt-last-print">Ultima impressao: ${formatDateTime(printedEntry.timestamp)} por ${escapeHtml(printedEntry.user.name)}</p>`
    : '';
  const isReprint = invoice.status === 'PAGO';
  const titleTxt = isReprint ? 'Re-imprimir Comprovante' : 'Comprovante de Recebimento';
  const descTxt = isReprint
    ? 'Nota ja foi lancada. Reimpressao gera novo comprovante sem alterar o status.'
    : 'Trilha completa + QR code + PDF original. Ao imprimir, registra o lancamento automaticamente.';
  const btnTxt = isReprint ? 'Re-imprimir Comprovante' : 'Imprimir e Lancar Nota';
  const btnClass = isReprint ? 'btn-ghost' : 'btn-primary';

  actionsEl.innerHTML = `
    <div class="receipt-card">
      <div class="receipt-card-icon">🖨</div>
      <div class="receipt-card-body">
        <strong>${titleTxt}</strong>
        <p>${descTxt}</p>
        ${lastPrint}
      </div>
      <div class="receipt-card-actions">
        <button class="btn ${btnClass}" id="drawer-finance-print">${btnTxt}</button>
      </div>
    </div>`;

  document.getElementById('drawer-finance-print').addEventListener('click', async () => {
    // Lancamento explicito (POST /mark-paid) so quando APROVADO. Reimpressao
    // de nota ja PAGO usa GET /print (sem efeito). Helper escolhe.
    if (!isReprint && !(await confirmAction('Confirmar recebimento e lancar a nota?'))) return;
    const { url, method } = _printOrMarkPaidEndpoint(invoice);
    const ok = await fetchAndOpenPdf(url, { method });
    if (ok) {
      showToast(isReprint ? 'Comprovante reimpresso.' : 'Comprovante gerado. Nota lancada.', 'success');
      setTimeout(async () => {
        const updated = await apiFetch(`/api/invoices/${invoice.id}`);
        _renderDrawerContent(updated);
        if (updated.has_attachment) _loadDrawerPdf(invoice.id);
      }, 1200);
    }
  });
}

function _wireDrawerReject(showId, sectionId, cancelId, txtId, confirmId, onConfirm) {
  document.getElementById(showId)?.addEventListener('click', () => {
    document.getElementById(sectionId)?.classList.remove('hidden');
    document.getElementById(showId)?.setAttribute('disabled', '');
  });
  document.getElementById(cancelId)?.addEventListener('click', () => {
    document.getElementById(sectionId)?.classList.add('hidden');
    document.getElementById(showId)?.removeAttribute('disabled');
  });
  const txt = document.getElementById(txtId);
  const confirmBtn = document.getElementById(confirmId);
  txt?.addEventListener('input', () => { if (confirmBtn) confirmBtn.disabled = txt.value.trim().length < 10; });
  confirmBtn?.addEventListener('click', async () => {
    const comment = txt.value.trim();
    if (comment.length < 10) return;
    try {
      await onConfirm(comment);
      showToast('Nota reprovada.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });
}

function _refreshAfterAction() {
  closeDrawer();
  setTimeout(() => window.location.reload(), 400);
}

async function _loadDrawerPdf(invoiceId) {
  const panel = document.getElementById('drawer-pdf-panel');
  if (!panel) return;
  try {
    const token = Auth.getToken();
    const resp = await fetch(`/api/invoices/${invoiceId}/attachment`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const iframe = document.getElementById('drawer-pdf-iframe');
    const link = document.getElementById('drawer-pdf-link');
    if (iframe) iframe.src = url;
    if (link) link.href = url;
    panel.style.display = 'block';
  } catch {}
}

// ── Admin Departments ────────────────────────────────────────────────────────

async function initAdminDepartments() {
  let editingDeptId = null;
  let allDirectors = [];

  async function loadDirectors() {
    try { allDirectors = await apiFetch('/api/admin/directors'); } catch { allDirectors = []; }
  }

  async function loadDepartments() {
    const list = document.getElementById('departments-list');
    try {
      const depts = await apiFetch('/api/admin/departments');
      if (!depts.length) {
        list.innerHTML = '<p class="text-muted" style="padding:1.5rem">Nenhum setor cadastrado ainda.</p>';
        return;
      }
      list.innerHTML = depts.map((d) => `
        <div class="card dept-card">
          <div class="dept-info">
            <strong>${escapeHtml(d.name)}</strong>
            ${d.description ? `<p class="text-muted">${escapeHtml(d.description)}</p>` : ''}
            <div class="dept-meta">
              <span>${d.members_count} membro${d.members_count !== 1 ? 's' : ''}</span>
              ${d.directors.length
                ? `<span>Diretores: ${d.directors.map((dr) => escapeHtml(dr.name)).join(', ')}</span>`
                : '<span class="text-muted">Sem diretor vinculado</span>'}
            </div>
          </div>
          <div class="dept-actions">
            <button class="btn btn-ghost btn-sm" data-edit="${d.id}">Editar</button>
            ${d.members_count === 0 ? `<button class="btn btn-ghost btn-sm text-danger" data-delete="${d.id}">Excluir</button>` : ''}
          </div>
        </div>`).join('');
      list.querySelectorAll('[data-edit]').forEach((btn) => {
        const dept = depts.find((d) => d.id === btn.dataset.edit);
        btn.addEventListener('click', () => openDeptModal(dept));
      });
      list.querySelectorAll('[data-delete]').forEach((btn) => {
        btn.addEventListener('click', () => deleteDept(btn.dataset.delete));
      });
    } catch (e) {
      list.innerHTML = `<p class="text-muted">Erro ao carregar setores: ${escapeHtml(e.message)}</p>`;
    }
  }

  function openDeptModal(dept) {
    editingDeptId = dept ? dept.id : null;
    document.getElementById('dept-modal-title').textContent = dept ? 'Editar Setor' : 'Novo Setor';
    document.getElementById('dept-name').value = dept ? dept.name : '';
    document.getElementById('dept-desc').value = dept ? (dept.description || '') : '';
    const container = document.getElementById('directors-checkboxes');
    const selectedIds = dept ? dept.directors.map((d) => d.id) : [];
    container.innerHTML = allDirectors.length
      ? allDirectors.map((d) => `<label class="checkbox-label">
          <input type="checkbox" value="${d.id}"${selectedIds.includes(d.id) ? ' checked' : ''}>
          ${escapeHtml(d.name)}</label>`).join('')
      : '<p class="text-muted">Nenhum diretor ativo cadastrado</p>';
    document.getElementById('dept-modal').classList.remove('hidden');
    document.getElementById('dept-name').focus();
  }

  function closeDeptModal() {
    document.getElementById('dept-modal').classList.add('hidden');
    editingDeptId = null;
  }

  async function saveDept() {
    const name = document.getElementById('dept-name').value.trim();
    if (!name) { showToast('Informe o nome do setor', 'error'); return; }
    const directorIds = [...document.querySelectorAll('#directors-checkboxes input:checked')].map((c) => c.value);
    const body = { name, description: document.getElementById('dept-desc').value.trim() || null, director_ids: directorIds };
    try {
      if (editingDeptId) {
        await apiFetch(`/api/admin/departments/${editingDeptId}`, { method: 'PUT', body: JSON.stringify(body) });
        showToast('Setor atualizado', 'success');
      } else {
        await apiFetch('/api/admin/departments', { method: 'POST', body: JSON.stringify(body) });
        showToast('Setor criado', 'success');
      }
      closeDeptModal();
      await loadDepartments();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function deleteDept(id) {
    if (!(await confirmAction('Excluir este setor?'))) return;
    try {
      await apiFetch(`/api/admin/departments/${id}`, { method: 'DELETE' });
      showToast('Setor excluido', 'success');
      await loadDepartments();
    } catch (e) { showToast(e.message, 'error'); }
  }

  await Promise.all([loadDirectors(), loadDepartments()]);

  document.getElementById('btn-new-dept').addEventListener('click', () => openDeptModal(null));
  document.getElementById('dept-modal-cancel').addEventListener('click', closeDeptModal);
  document.getElementById('dept-modal-save').addEventListener('click', saveDept);
  document.getElementById('dept-modal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('dept-modal')) closeDeptModal();
  });
}

// ── Listeners globais (ESC fecha modal, click no backdrop fecha) ────────────

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    // Fecha o ultimo modal visivel (z-index mais alto)
    const open = document.querySelectorAll('.modal-backdrop:not(.hidden)');
    if (open.length) {
      open[open.length - 1].classList.add('hidden');
      event.stopPropagation();
    }
    // Fecha drawer aberto
    const drawer = document.querySelector('.drawer-backdrop:not(.hidden)');
    if (drawer) drawer.classList.add('hidden');
  }
});
document.addEventListener('click', (event) => {
  // Click no backdrop (nao no conteudo interno) fecha o modal
  if (event.target.classList?.contains('modal-backdrop')) {
    event.target.classList.add('hidden');
  }
  if (event.target.classList?.contains('drawer-backdrop')) {
    event.target.classList.add('hidden');
  }
});


// ── DOMContentLoaded dispatch ────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', async () => {
  const page = document.body.dataset.page;
  if (page === 'login') {
    // Token vive em memoria desde P1-1; reload chega sem token. Se temos
    // hint de sessao, tenta renovar antes — usuario que ja estava logado
    // em outra aba nao deve ver o /login.
    if (!Auth.getToken() && Auth.hasSessionHint()) {
      try { await Auth.ensureToken(); } catch (e) {}
    }
    if (Auth.getToken()) {
      // Se chegou aqui com ?next=, manda direto pra la (caso usuario clique
      // 'Entrar' no /verify mas ja tem sessao ativa em outra aba).
      window.location.href = getSafeNextParam() || '/dashboard';
    }
    document.getElementById('login-form')?.addEventListener('submit', handleLogin);
    document.getElementById('toggle-password')?.addEventListener('click', togglePasswordVisibility);
    return;
  }
  // Paginas autenticadas: hidrata token em memoria via cookie de refresh
  // antes do primeiro fetch. Sem isso, todo F5 dispararia 401 -> retry,
  // gastando uma rodada extra. Falha aqui nao redireciona — apiFetch ja
  // cuida do fluxo de 401 se ainda nao deu pra refresh.
  if (!Auth.getToken() && Auth.hasSessionHint()) {
    try { await Auth.ensureToken(); } catch (e) {}
  }
  if (page === 'change-password') {
    if (window.Economart?.password?.initChange) {
      window.Economart.password.initChange();
    } else {
      console.error('[dispatch] password.js nao carregado — verifique <script> do template change_password.html');
    }
    return;
  }
  document.getElementById('sidebar-toggle')?.addEventListener('click', toggleSidebar);
  document.getElementById('logout-btn')?.addEventListener('click', logout);

  // Global drawer delegation — any [data-drawer] button opens the slide-in drawer
  document.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-drawer]');
    if (btn) {
      event.preventDefault();
      openInvoiceDrawer(btn.dataset.drawer);
    }
  });

  if (page === 'dashboard') {
    // dashboard-v2.js cuida do dashboard novo; aqui so o shell.
    initShell();
  } else if (page === 'invoices-list') {
    initShell().then(() => initInvoicesList());
  } else if (page === 'invoice-create') {
    initShell().then(() => initInvoiceForm('create'));
  } else if (page === 'invoice-edit') {
    initShell().then(() => initInvoiceForm('edit'));
  } else if (page === 'invoice-detail') {
    initShell().then(() => initInvoiceDetail());
  } else if (page === 'alerts') {
    initShell().then(() => initAlertsPage());
  } else if (page === 'manager-queue') {
    initShell().then(() => initReviewQueue('manager'));
  } else if (page === 'director-queue') {
    initShell().then(() => initReviewQueue('director'));
  } else if (page === 'manager-detail') {
    initShell().then(() => initReviewDetail('manager'));
  } else if (page === 'director-detail') {
    initShell().then(() => initReviewDetail('director'));
  } else if (page === 'finance-queue') {
    initShell().then(() => initFinanceQueue());
  } else if (page === 'finance-detail') {
    initShell().then(() => initFinanceDetail());
  } else if (page === 'admin-users') {
    initShell().then(() => initAdminUsers());
  } else if (page === 'admin-user-form') {
    initShell().then(() => initAdminUserForm());
  } else if (page === 'admin-audit-logs') {
    initShell().then(() => initAdminAuditLogs());
  } else if (page === 'admin-departments') {
    initShell().then(() => initAdminDepartments());
  } else if (page === 'configuracoes') {
    initShell().then(() => initConfiguracoes());
  } else if (page === 'forgot-password') {
    if (window.Economart?.password?.initForgot) {
      window.Economart.password.initForgot();
    } else {
      console.error('[dispatch] password.js nao carregado em forgot_password.html');
    }
  } else if (page === 'reset-password') {
    if (window.Economart?.password?.initReset) {
      window.Economart.password.initReset();
    } else {
      console.error('[dispatch] password.js nao carregado em reset_password.html');
    }
  } else if (document.querySelector('.layout')) {
    initShell();
  }
});


// initForgotPasswordPage e initResetPasswordPage movidas para
// app/static/js/password.js (P2-1 auditoria). Acesso via
// window.Economart.password.initForgot() e .initReset().


// SMTP config foi removido da UI — agora vive em .env (so quem opera
// o Railway pode editar). Removidas as funcoes initAdminSmtp,
// loadAdminSmtp, saveAdminSmtp, testSmtp, populateSmtpForm.
