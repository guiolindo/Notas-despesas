/* alerts.js — pagina de alertas (/alerts). */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  window.Economart.alerts = { initAlertsPage, isWithinDateRange };
  window.initAlertsPage = initAlertsPage;
  window.isWithinDateRange = isWithinDateRange;
})();
