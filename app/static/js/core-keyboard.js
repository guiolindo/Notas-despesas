/* core-keyboard.js — atalhos de teclado globais + cheatsheet.
 *
 * Depende de window.Auth.getUser() para perfis (CONTAS_A_PAGAR/FINANCE
 * nao tem atalho 'n' pra nova nota).
 *
 * P2-1 v3 (auditoria, jun/2026): split do core.js (Fase 3).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  window.Economart.core = window.Economart.core || {};
  window.Economart.core._wireGlobalShortcuts = _wireGlobalShortcuts;
  window._wireGlobalShortcuts = _wireGlobalShortcuts;
})();
