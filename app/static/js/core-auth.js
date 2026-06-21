/* core-auth.js — Auth closure + pre-warm /refresh + edit listener.
 *
 * Carregar DEPOIS de core.js (que cria window.Economart) e ANTES de
 * core-api.js (que usa Auth.getToken()).
 *
 * P2-1 v3 (auditoria, jun/2026): split do core.js em sub-modulos (Fase 3).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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
  window.Economart.core = window.Economart.core || {};
  window.Economart.core.Auth = Auth;

  // ── Listener global: marca intencao de editar usuario admin ──────────
  // Quando o admin clica em "Editar" na lista (/admin/users), grava
  // sessionStorage com o ID alvo. A pagina de edit consulta esse flag pra
  // confirmar que o usuario veio via UI (e nao via historico/URL colada).
  document.addEventListener('click', (event) => {
    const a = event.target.closest && event.target.closest('a[href]');
    if (!a) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/admin\/users\/([^/?#]+)\/edit\b/);
    if (m) {
      try { sessionStorage.setItem('admin_edit_target_id', m[1]); } catch (e) {}
    }
  });

  // Pre-aquece /auth/refresh assim que carrega — antes do DOMContentLoaded.
  // Em redes/instancias com cold start (Railway free tier), o /refresh
  // pode demorar 3-8s. Disparando aqui no topo do parsing, ate o
  // DOMContentLoaded disparar e o usuario clicar em algo, o token tipicamente
  // ja chegou.
  try {
    if (Auth.hasSessionHint && Auth.hasSessionHint()) {
      Auth.ensureToken().catch(() => {});
    }
  } catch (e) {}
})();
