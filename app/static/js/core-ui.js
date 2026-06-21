/* core-ui.js — UI helpers: toast, loading, confirm, withButtonLoading,
 * toggleSidebar + sidebar mobile + listeners globais ESC/backdrop click.
 *
 * P2-1 v3 (auditoria, jun/2026): split do core.js (Fase 3).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  /** Desabilita o botao + troca texto enquanto a acao roda, restaura depois.
   *  Codex sugeriu este padrao no chat de coordenacao: usuario reportou
   *  sensacao de app travado em acoes lentas (5s de lag); botao sem
   *  feedback visual parece morto. */
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
      // Iframes nativos de PDF (Chrome/Edge) ignoram z-index — escondemos
      // enquanto o modal estiver aberto.
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

  // ── Sidebar mobile ─────────────────────────────────────────────────
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

  // Namespace + aliases
  window.Economart.core = window.Economart.core || {};
  Object.assign(window.Economart.core, {
    showToast, showLoading, hideLoading, withButtonLoading, confirmAction,
    toggleSidebar, _wireSidebarMobile,
  });
  window.showToast = showToast;
  window.showLoading = showLoading;
  window.hideLoading = hideLoading;
  window.withButtonLoading = withButtonLoading;
  window.confirmAction = confirmAction;
  window.toggleSidebar = toggleSidebar;
  window._wireSidebarMobile = _wireSidebarMobile;
})();
