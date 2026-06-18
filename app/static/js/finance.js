/* finance.js — fluxo financeiro: fila + detalhe + lancamento.
 * Depende de pdf-viewer.js (fetchAndOpenPdf), invoice-detail.js (renderInvoiceDetail).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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
      state.dueFrom = ''; state.dueTo = '';
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
    document.getElementById('print-invoice-btn')?.addEventListener('click', async (ev) => {
      if (!(await confirmAction(`Confirmar lancamento da nota ${invoice.invoice_number}? Esta acao sera registrada e nao pode ser desfeita.`))) return;
      await withButtonLoading(
        ev.currentTarget,
        'Lancando...',
        async () => {
          const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/mark-paid`, { method: 'POST' });
          if (ok) {
            showToast('Comprovante gerado. Recebimento registrado no sistema.', 'success');
            setTimeout(() => window.location.reload(), 1800);
          }
          return ok;
        },
        { keepDisabledOnSuccess: true, successText: 'Lancado' }
      );
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

  window.Economart.finance = {
    initFinanceQueue, initFinanceDetail, daysUntil, daysBadge,
  };
  window.initFinanceQueue = initFinanceQueue;
  window.initFinanceDetail = initFinanceDetail;
  window.daysUntil = daysUntil;
  window.daysBadge = daysBadge;
})();
