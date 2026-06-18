/* admin-audit.js — visualizador de audit logs (admin). */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  let adminAuditState = { page: 1, pages: 1, filters: {} };

  async function initAdminAuditLogs() {
    await loadAdminAuditUsers();
    document.getElementById('admin-audit-filter-form')?.addEventListener('submit', (event) => {
      event.preventDefault();
      adminAuditState.page = 1;
      adminAuditState.filters = readAdminAuditFilters();
      loadAdminAuditLogs();
    });
    document.getElementById('admin-audit-clear')?.addEventListener('click', () => {
      document.getElementById('admin-audit-filter-form').reset();
      adminAuditState.page = 1;
      adminAuditState.filters = {};
      loadAdminAuditLogs();
    });
    document.getElementById('admin-audit-prev')?.addEventListener('click', () => {
      if (adminAuditState.page > 1) {
        adminAuditState.page -= 1;
        loadAdminAuditLogs();
      }
    });
    document.getElementById('admin-audit-next')?.addEventListener('click', () => {
      if (adminAuditState.page < adminAuditState.pages) {
        adminAuditState.page += 1;
        loadAdminAuditLogs();
      }
    });
    await loadAdminAuditLogs();
  }

  async function loadAdminAuditUsers() {
    const select = document.getElementById('admin-audit-user');
    if (!select) return;
    try {
      const users = await apiFetch('/api/admin/users');
      users.forEach((user) => {
        const option = document.createElement('option');
        option.value = user.id;
        option.textContent = `${user.name} (${user.email})`;
        select.appendChild(option);
      });
    } catch (error) { showToast(error.message, 'error'); }
  }

  function readAdminAuditFilters() {
    return {
      action: document.getElementById('admin-audit-action').value.trim(),
      user_id: document.getElementById('admin-audit-user').value,
      success: document.getElementById('admin-audit-success').value
    };
  }

  async function loadAdminAuditLogs() {
    const params = new URLSearchParams({
      page: adminAuditState.page,
      per_page: 50,
      ...adminAuditState.filters
    });
    [...params.entries()].forEach(([key, value]) => {
      if (!value) params.delete(key);
    });
    try {
      const data = await apiFetch(`/api/admin/audit-logs?${params.toString()}`);
      adminAuditState.pages = data.pages || 1;
      renderAdminAuditLogs(data);
    } catch (error) { showToast(error.message, 'error'); }
  }

  function renderAdminAuditLogs(data) {
    const tbody = document.getElementById('admin-audit-tbody');
    if (!tbody) return;
    document.getElementById('admin-audit-total').textContent = `${data.total} registros`;
    document.getElementById('admin-audit-page').textContent = `Pagina ${data.page} de ${adminAuditState.pages}`;
    document.getElementById('admin-audit-prev').disabled = data.page <= 1;
    document.getElementById('admin-audit-next').disabled = data.page >= adminAuditState.pages;
    if (!data.items.length) {
      tbody.innerHTML = '<tr><td colspan="6">Nenhum log encontrado.</td></tr>';
      return;
    }
    tbody.innerHTML = data.items.map((log) => `
      <tr class="audit-row" data-log-id="${log.id}">
        <td>${formatDateTime(log.timestamp)}</td>
        <td>${escapeHtml(log.user_name || 'Sistema')}<div class="table-subtext">${escapeHtml(log.user_email || '')}</div></td>
        <td><span class="audit-action-badge">${escapeHtml(log.action)}</span></td>
        <td>${escapeHtml(log.resource_type || '-')}${log.resource_id ? `<div class="table-subtext">${escapeHtml(log.resource_id)}</div>` : ''}</td>
        <td>${escapeHtml(log.ip_address || '-')}</td>
        <td>${log.success ? '<span class="status-badge user-status-active">Sucesso</span>' : '<span class="status-badge user-status-inactive">Falha</span>'}</td>
      </tr>
      <tr class="audit-detail-row hidden" data-detail-for="${log.id}">
        <td colspan="6">${escapeHtml(log.detail || 'Sem detalhes.')}</td>
      </tr>
    `).join('');
    tbody.querySelectorAll('.audit-row').forEach((row) => {
      row.addEventListener('click', () => {
        tbody.querySelector(`[data-detail-for="${row.dataset.logId}"]`)?.classList.toggle('hidden');
      });
    });
  }

  window.Economart.adminAudit = { initAdminAuditLogs };
  window.initAdminAuditLogs = initAdminAuditLogs;
})();
