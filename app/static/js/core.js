/* core.js — base de tudo: Auth, apiFetch, UI helpers, banner offline,
 * service worker, atalhos globais, listeners ESC/backdrop.
 *
 * Carregar PRIMEIRO depois de format.js e documents.js.
 * Outros modulos dependem de window.Auth, window.apiFetch, window.showToast,
 * window.confirmAction, etc.
 *
 * P2-1 v3 (auditoria): split do antigo app.js monolitico (3712 linhas).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  // ─── Barra de progresso global ─────────────────────────────────────
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
        if (url.href === location.href) return false;
      } catch (e) { return false; }
      return true;
    }
    document.addEventListener('click', function(ev) {
      const a = ev.target.closest('a[href]');
      if (isInternalLink(a, ev)) start();
    });
    document.addEventListener('submit', function(ev) {
      const f = ev.target;
      if (!f || f.tagName !== 'FORM') return;
      if (f.dataset.noProgress === '1') return;
      if (f.target && f.target !== '_self') return;
      setTimeout(() => { if (!ev.defaultPrevented) start(); }, 0);
    }, true);
    window.addEventListener('pageshow', finish);
    if (document.readyState === 'complete') finish();
    else window.addEventListener('load', finish);
  })();

  // ─── Auth helper ───────────────────────────────────────────────────
  // P1-1 da auditoria: access token em memoria, refresh via cookie HttpOnly.
  const Auth = (() => {
    let _accessToken = null;
    let _refreshPromise = null;
    const SESSION_KEY = 'auth_has_session';
    const markSession = () => { try { sessionStorage.setItem(SESSION_KEY, '1'); } catch (e) {} };
    const unmarkSession = () => { try { sessionStorage.removeItem(SESSION_KEY); } catch (e) {} };
    const hasSessionHint = () => {
      try { return sessionStorage.getItem(SESSION_KEY) === '1'; } catch (e) { return false; }
    };
    async function _doRefresh() {
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
    async function ensureToken() {
      if (_accessToken) return _accessToken;
      if (!_refreshPromise) {
        _refreshPromise = _doRefresh().finally(() => { _refreshPromise = null; });
      }
      return _refreshPromise;
    }
    // Migracao defensiva: token legado no localStorage vira sessao hint.
    try {
      const legacyToken = localStorage.getItem('access_token');
      if (legacyToken !== null) {
        localStorage.removeItem('access_token');
        markSession();
      }
      if (localStorage.getItem('user')) markSession();
    } catch (e) {}
    return {
      getToken: () => _accessToken,
      setToken: (token) => {
        _accessToken = token || null;
        if (_accessToken) markSession(); else unmarkSession();
      },
      removeToken: () => { _accessToken = null; unmarkSession(); },
      ensureToken,
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
  window.Auth = Auth;

  // ── Listener global: marca intencao de editar usuario admin ──────────
  document.addEventListener('click', (event) => {
    const a = event.target.closest && event.target.closest('a[href]');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/admin\/users\/([^/?#]+)\/edit\b/);
    if (m) {
      try { sessionStorage.setItem('admin_edit_target_id', m[1]); } catch (e) {}
    }
  });

  // ── Detector de conexao ─────────────────────────────────────────────
  (function setupOfflineBanner() {
    let bannerEl = null;
    let isShown = false;
    let serverDown = false;
    let _hideTimer = null;
    function ensureBanner() {
      if (bannerEl) return bannerEl;
      bannerEl = document.createElement('div');
      bannerEl.id = 'offline-banner';
      bannerEl.setAttribute('role', 'status');
      bannerEl.setAttribute('aria-live', 'polite');
      bannerEl.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0',
        'background:#fef3c7', 'color:#92400e',
        'border-bottom:1px solid #fbbf24',
        'padding:10px 16px',
        'font-size:14px', 'font-weight:500',
        'text-align:center',
        'z-index:9999',
        'box-shadow:0 1px 3px rgba(0,0,0,0.1)',
        'transform:translateY(-100%)',
        'transition:transform .25s ease',
        'pointer-events:none',
      ].join(';');
      bannerEl.innerHTML = (
        '<span style="margin-right:8px">📡</span>' +
        '<strong>Sem conexao com a internet.</strong> ' +
        'Verifique seu Wi-Fi ou dados moveis. ' +
        '<span id="offline-banner-status" style="opacity:.7;margin-left:8px"></span>'
      );
      document.body.appendChild(bannerEl);
      return bannerEl;
    }
    function show(reason) {
      if (_hideTimer) { clearTimeout(_hideTimer); _hideTimer = null; }
      const el = ensureBanner();
      if (!isShown) {
        isShown = true;
        void el.offsetHeight;
        el.style.transform = 'translateY(0)';
      }
      const statusEl = document.getElementById('offline-banner-status');
      if (statusEl && reason) statusEl.textContent = `(${reason})`;
    }
    function hide(force) {
      if (!isShown || !bannerEl) return;
      if (!force && typeof navigator !== 'undefined' && navigator.onLine === false) return;
      if (!force && serverDown) return;
      if (_hideTimer) clearTimeout(_hideTimer);
      _hideTimer = setTimeout(() => {
        _hideTimer = null;
        isShown = false;
        if (bannerEl) bannerEl.style.transform = 'translateY(-100%)';
      }, 600);
    }
    window.addEventListener('offline', () => {
      serverDown = false;
      show('sem internet');
    });
    window.addEventListener('online', () => {
      serverDown = false;
      hide(true);
      try {
        if (sessionStorage.getItem('was_offline') === '1') {
          sessionStorage.removeItem('was_offline');
          setTimeout(() => window.location.reload(), 300);
        }
      } catch (e) {}
    });
    if (typeof navigator !== 'undefined' && navigator.onLine === false) {
      if (document.body) {
        show('sem internet');
      } else {
        document.addEventListener('DOMContentLoaded', () => show('sem internet'));
      }
    }
    window.addEventListener('app:network-error', () => {
      serverDown = true;
      show('servidor inacessivel');
    });
    window.addEventListener('app:network-ok', () => {
      serverDown = false;
      hide(false);
    });
  })();

  // ── Service Worker (PWA / offline) ─────────────────────────────────
  (function registerServiceWorker() {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return;
    if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') return;
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js', { scope: '/' })
        .then((reg) => {
          reg.addEventListener('updatefound', () => {
            const sw = reg.installing;
            if (!sw) return;
            sw.addEventListener('statechange', () => {
              if (sw.state === 'activated' && navigator.serviceWorker.controller) {
                console.log('[sw] atualizado pra nova versao');
              }
            });
          });
        })
        .catch((err) => console.warn('[sw] falha ao registrar:', err));
    });
    let refreshing = false;
    navigator.serviceWorker.addEventListener('controllerchange', () => {
      if (refreshing) return;
      refreshing = true;
      window.location.reload();
    });
  })();

  // Pre-aquece /auth/refresh assim que carrega — antes do DOMContentLoaded.
  try {
    if (Auth.hasSessionHint && Auth.hasSessionHint()) {
      Auth.ensureToken().catch(() => {});
    }
  } catch (e) {}

  // ── apiFetch + submitInvoiceWithDuplicateCheck ─────────────────────
  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    let token = Auth.getToken();
    if (!token) token = await Auth.ensureToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);

    let response;
    try {
      response = await fetch(url, { ...options, headers, credentials: 'include' });
      window.dispatchEvent(new CustomEvent('app:network-ok'));
    } catch (netErr) {
      window.dispatchEvent(new CustomEvent('app:network-error'));
      const err = new Error('Sem conexao com o servidor. Verifique sua internet.');
      err.networkError = true;
      err.cause = netErr;
      throw err;
    }
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
    if (response.status === 428) {
      if (window.location.pathname !== '/change-password') {
        window.location.href = '/change-password';
      }
      throw new Error('Troca de senha obrigatoria antes de continuar.');
    }
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      if (response.status >= 500) {
        console.error('[apiFetch] 5xx:', response.status, data);
        throw new Error('Erro no servidor. Tente novamente em alguns segundos.');
      }
      if (Array.isArray(data?.detail)) {
        const first = data.detail[0];
        const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : '';
        throw new Error(field ? `${field}: ${first.msg}` : (first?.msg || 'Dados invalidos'));
      }
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

  // ── UI helpers ─────────────────────────────────────────────────────
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

  async function withButtonLoading(button, loadingText, fn, opts) {
    if (!button) return fn();
    opts = opts || {};
    const prevText = button.textContent;
    const prevDisabled = button.disabled;
    button.disabled = true;
    button.textContent = loadingText || 'Aguarde...';
    button.classList.add('is-loading');
    let result;
    let ok = false;
    try {
      result = await fn();
      ok = true;
      return result;
    } finally {
      if (opts.keepDisabledOnSuccess && ok && result) {
        if (opts.successText) button.textContent = opts.successText;
        button.classList.remove('is-loading');
      } else {
        button.disabled = prevDisabled;
        button.textContent = prevText;
        button.classList.remove('is-loading');
      }
    }
  }

  function confirmAction(message) {
    return new Promise((resolve) => {
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

  // ── Sidebar (mobile drawer) ────────────────────────────────────────
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

  // ── Atalhos de teclado globais ─────────────────────────────────────
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
  let _shortcutPrefix = null;
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
        document.querySelector('.drawer.open, .drawer-open')?.classList.remove('open', 'drawer-open');
        document.getElementById('shortcuts-modal-backdrop')?.remove();
      }
    });
  }

  // ── Helpers de path/validacao ──────────────────────────────────────
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

  const ROLE_LABELS = {
    ADMIN:           'Administrador',
    MANAGER:         'Gestor',
    DIRECTOR:        'Diretor',
    FINANCE:         'Financeiro',
    EMPLOYEE:        'Funcionario',
    CONTAS_A_PAGAR:  'Contas a Pagar',
  };

  // ── Listeners globais ESC/click backdrop ───────────────────────────
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      const open = document.querySelectorAll('.modal-backdrop:not(.hidden)');
      if (open.length) {
        open[open.length - 1].classList.add('hidden');
        event.stopPropagation();
      }
      const drawer = document.querySelector('.drawer-backdrop:not(.hidden)');
      if (drawer) drawer.classList.add('hidden');
    }
  });
  document.addEventListener('click', (event) => {
    if (event.target.classList?.contains('modal-backdrop')) {
      event.target.classList.add('hidden');
    }
    if (event.target.classList?.contains('drawer-backdrop')) {
      event.target.classList.add('hidden');
    }
  });

  // ── Exposicao no namespace + aliases globais ───────────────────────
  window.Economart.core = {
    apiFetch, submitInvoiceWithDuplicateCheck,
    showToast, showLoading, hideLoading, withButtonLoading, confirmAction,
    toggleSidebar, _wireSidebarMobile, _wireGlobalShortcuts,
    getInvoiceIdFromPath, invoiceApiPath, validatePassword,
    ROLE_LABELS,
  };
  // Aliases globais (compat — modulos referenciam pelo nome curto)
  window.apiFetch = apiFetch;
  window.submitInvoiceWithDuplicateCheck = submitInvoiceWithDuplicateCheck;
  window.showToast = showToast;
  window.showLoading = showLoading;
  window.hideLoading = hideLoading;
  window.withButtonLoading = withButtonLoading;
  window.confirmAction = confirmAction;
  window.toggleSidebar = toggleSidebar;
  window._wireSidebarMobile = _wireSidebarMobile;
  window._wireGlobalShortcuts = _wireGlobalShortcuts;
  window.getInvoiceIdFromPath = getInvoiceIdFromPath;
  window.invoiceApiPath = invoiceApiPath;
  window.validatePassword = validatePassword;
  window.ROLE_LABELS = ROLE_LABELS;
})();
