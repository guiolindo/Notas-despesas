/* core.js — bootstrap minimo + helpers utilitarios.
 *
 * Apos split jun/2026 (Fase 3 do plan-refactor-master), o core grande
 * virou facade pequena. Carrega PRIMEIRO entre os modulos do core, depois
 * de format.js e documents.js:
 *
 *   1. format.js          (helpers puros)
 *   2. documents.js       (CPF/CNPJ)
 *   3. core.js            ← este (bootstrap namespace + helpers comuns)
 *   4. core-auth.js       (Auth closure + pre-warm /refresh)
 *   5. core-api.js        (apiFetch + submitInvoice)
 *   6. core-ui.js         (toast, loading, confirm, sidebar mobile, listeners ESC)
 *   7. core-network.js    (nav progress + offline banner + service worker)
 *   8. core-keyboard.js   (atalhos globais + cheatsheet)
 *   9. shell.js           (initShell + login + configuracoes)
 *  10. ... resto
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  // Namespace canonico
  window.Economart.core = window.Economart.core || {};
  Object.assign(window.Economart.core, {
    getInvoiceIdFromPath, invoiceApiPath, validatePassword, ROLE_LABELS,
  });
  // Aliases globais
  window.getInvoiceIdFromPath = getInvoiceIdFromPath;
  window.invoiceApiPath = invoiceApiPath;
  window.validatePassword = validatePassword;
  window.ROLE_LABELS = ROLE_LABELS;
})();
