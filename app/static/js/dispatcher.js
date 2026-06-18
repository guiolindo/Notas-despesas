/* dispatcher.js — DOMContentLoaded router.
 * Carregar POR ULTIMO (depois de todos os modulos).
 * Le data-page do <body> e chama o init* correspondente.
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;

  document.addEventListener('DOMContentLoaded', async () => {
    const page = document.body.dataset.page;
    if (page === 'login') {
      const nextParam = getSafeNextParam();
      // Auto-redirect somente quando NAO ha ?next= (preserva intencao do usuario).
      if (!nextParam) {
        if (!Auth.getToken() && Auth.hasSessionHint()) {
          try { await Auth.ensureToken(); } catch (e) {}
        }
        if (Auth.getToken()) {
          window.location.href = '/dashboard';
          return;
        }
      }
      document.getElementById('login-form')?.addEventListener('submit', handleLogin);
      document.getElementById('toggle-password')?.addEventListener('click', togglePasswordVisibility);
      return;
    }
    // Paginas autenticadas: hidrata token via cookie de refresh
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

    // Drawer delegation — qualquer [data-drawer] abre o slide-in
    document.addEventListener('click', (event) => {
      const btn = event.target.closest('[data-drawer]');
      if (btn) {
        event.preventDefault();
        openInvoiceDrawer(btn.dataset.drawer);
      }
    });

    if (page === 'dashboard') {
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
})();
