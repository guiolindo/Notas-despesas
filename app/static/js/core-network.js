/* core-network.js — nav progress bar + offline banner + service worker.
 *
 * P2-1 v3 (auditoria, jun/2026): split do core.js (Fase 3).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;

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
})();
