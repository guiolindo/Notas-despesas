/* invoices-list.js — listagem de notas (/invoices).
 * Depende de window.Auth, window.apiFetch, window.showToast, window.confirmAction,
 * window.escapeHtml, window.formatDate, window.formatCurrency, window.statusBadge.
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  let invoiceListState = {
    page: 1, perPage: 20, pages: 1,
    status: '', search: '',
    fromDate: '', toDate: '', dueFrom: '', dueTo: '',
    minAmount: '', maxAmount: '',
    createdBy: '', supplier: '', departmentId: '',
  };
  let _invoicesSearchDebounce = null;

  async function initInvoicesList() {
    const _u = Auth.getUser();
    if (_u && ['CONTAS_A_PAGAR', 'FINANCE'].includes(_u.role)) {
      document.getElementById('btn-new-invoice')?.remove();
    }
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
    document.getElementById('status-filter')?.addEventListener('change', (event) => {
      invoiceListState.status = event.target.value;
      triggerReload();
    });
    document.getElementById('invoices-search')?.addEventListener('input', (event) => {
      invoiceListState.search = event.target.value;
      clearTimeout(_invoicesSearchDebounce);
      _invoicesSearchDebounce = setTimeout(triggerReload, 300);
    });
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
    document.getElementById('invoices-toggle-advanced')?.addEventListener('click', () => {
      document.getElementById('invoices-advanced')?.classList.toggle('hidden');
    });
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
        const sample = await apiFetch('/api/invoices/?per_page=100');
        const seen = new Map();
        (sample.items || []).forEach((it) => {
          if (it.department_name) seen.set(it.department_name, { id: it.department_name, name: it.department_name });
        });
        depts = Array.from(seen.values());
      }
      depts.forEach((d) => {
        const opt = document.createElement('option');
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

  window.Economart.invoicesList = { initInvoicesList };
  window.initInvoicesList = initInvoicesList;
})();
