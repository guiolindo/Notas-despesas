const Auth = {
  getToken: () => localStorage.getItem('access_token'),
  setToken: (token) => localStorage.setItem('access_token', token),
  removeToken: () => localStorage.removeItem('access_token'),
  getUser: () => JSON.parse(localStorage.getItem('user') || 'null'),
  setUser: (user) => localStorage.setItem('user', JSON.stringify(user)),
  clear: () => {
    Auth.removeToken();
    localStorage.removeItem('user');
  }
};

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  const token = Auth.getToken();
  if (token) headers.set('Authorization', `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }

  const response = await fetch(url, { ...options, headers, credentials: 'include' });
  if (response.status === 401) {
    Auth.clear();
    window.location.href = '/login';
    throw new Error('Sessao expirada');
  }

  const contentType = response.headers.get('content-type') || '';
  const data = contentType.includes('application/json') ? await response.json() : await response.text();
  if (!response.ok) {
    // Erros 5xx vem com detail tecnico/stacktrace ou HTML. Mostra mensagem
    // amigavel pro usuario; o detalhe vai pro console pra debug.
    if (response.status >= 500) {
      console.error('[apiFetch] 5xx:', response.status, data);
      throw new Error('Erro no servidor. Tente novamente em alguns segundos.');
    }
    // Erros de validacao do Pydantic vem como array [{loc, msg, type}]
    if (Array.isArray(data?.detail)) {
      const first = data.detail[0];
      const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : '';
      throw new Error(field ? `${field}: ${first.msg}` : (first?.msg || 'Dados invalidos'));
    }
    throw new Error(data?.detail || (typeof data === 'string' ? data : null) || 'Erro na requisicao');
  }
  return data;
}

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

const TZ = 'America/Sao_Paulo';

function formatDate(dateStr) {
  if (!dateStr) return '-';
  return new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC' }).format(new Date(`${dateStr}T00:00:00Z`));
}

function formatDateTime(dateStr) {
  if (!dateStr) return '-';
  return new Intl.DateTimeFormat('pt-BR', {
    timeZone: TZ,
    dateStyle: 'short',
    timeStyle: 'short'
  }).format(new Date(dateStr));
}

/** Retorna a hora atual no fuso horário de Brasilia (0-23). */
function hourInBR() {
  return parseInt(new Intl.DateTimeFormat('en-US', { timeZone: TZ, hour: 'numeric', hour12: false }).format(new Date()), 10);
}

/** Retorna a string YYYY-MM-DD de hoje em Brasilia. */
function todayInBR() {
  return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date());
}

function formatCurrency(value) {
  return new Intl.NumberFormat('pt-BR', {
    style: 'currency',
    currency: 'BRL'
  }).format(Number(value || 0));
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#039;'
  })[char]);
}

function statusBadge(status) {
  const text = {
    RASCUNHO: 'Rascunho',
    AGUARDANDO_GESTOR: 'Aguardando gestor',
    REPROVADO_GESTOR: 'Reprovado gestor',
    AGUARDANDO_DIRETOR: 'Aguardando diretor',
    REPROVADO_DIRETOR: 'Reprovado diretor',
    APROVADO: 'Aprovado',
    PAGO: 'Lancado'
  }[status] || status;
  return `<span class="status-badge status-${String(status).toLowerCase()}">${text}</span>`;
}

function confirmAction(message) {
  return new Promise((resolve) => {
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
      resolve(action === 'confirm');
    });
  });
}

function toggleSidebar() {
  document.getElementById('sidebar')?.classList.toggle('collapsed');
}

async function logout() {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } finally {
    Auth.clear();
    window.location.href = '/login';
  }
}

function togglePasswordVisibility() {
  const input = document.getElementById('password');
  if (input) input.type = input.type === 'password' ? 'text' : 'password';
}

async function handleLogin(event) {
  event.preventDefault();
  const button = document.getElementById('login-btn');
  const errorEl = document.getElementById('login-error');
  errorEl.classList.add('hidden');
  button.disabled = true;
  button.textContent = 'Entrando...';

  try {
    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        email: document.getElementById('email').value,
        password: document.getElementById('password').value
      })
    });
    const data = await response.json();
    if (!response.ok) {
      errorEl.textContent = data.detail || 'Erro ao fazer login';
      errorEl.classList.remove('hidden');
      return;
    }
    Auth.setToken(data.access_token);
    Auth.setUser(data.user);
    window.location.href = data.user.must_change_password ? '/change-password' : '/dashboard';
  } catch {
    errorEl.textContent = 'Erro de conexao. Tente novamente.';
    errorEl.classList.remove('hidden');
  } finally {
    button.disabled = false;
    button.textContent = 'Entrar';
  }
}

const ROLE_LABELS = {
  ADMIN:     'Administrador',
  MANAGER:   'Gestor',
  DIRECTOR:  'Diretor',
  FINANCE:   'Financeiro',
  EMPLOYEE:  'Funcionario',
};

async function initShell() {
  let user = Auth.getUser();
  if (!user) { window.location.href = '/login'; return; }

  // Atualiza dados do usuario a cada pagina (pega must_change_password e submit_directly_to_director frescos)
  try {
    const fresh = await apiFetch('/auth/me');
    user = { ...user, ...fresh };
    Auth.setUser(user);
  } catch {
    // Se falhar (token expirado o apiFetch já redireciona para /login)
  }

  // Redireciona para trocar senha se obrigatorio
  if (user.must_change_password && window.location.pathname !== '/change-password') {
    window.location.href = '/change-password';
    return;
  }

  document.getElementById('app-layout').style.visibility = 'visible';
  document.getElementById('header-user-name').textContent = user.name;
  document.getElementById('header-user-role').textContent = ROLE_LABELS[user.role] || user.role;
  addApprovalQueueLink(user.role);
  renderGlobalAvailabilityBanner();
  try {
    const data = await apiFetch('/alerts/');
    const count = data.summary.total_alerts;
    if (count > 0) {
      const el = document.getElementById('alert-count');
      el.textContent = count;
      el.classList.remove('hidden');
    }
  } catch {}
}

function addApprovalQueueLink(role) {
  const nav = document.querySelector('.sidebar-nav');
  if (!nav) return;
  if (role === 'ADMIN' && !document.getElementById('nav-admin-users')) {
    document.getElementById('nav-admin')?.remove();
    const users = document.createElement('a');
    users.href = '/admin/users';
    users.id = 'nav-admin-users';
    users.className = 'nav-item';
    users.innerHTML = '<span class="nav-icon">&#9786;</span> Usuarios';
    const depts = document.createElement('a');
    depts.href = '/admin/departments';
    depts.id = 'nav-admin-depts';
    depts.className = 'nav-item';
    depts.innerHTML = '<span class="nav-icon">&#9670;</span> Setores';
    const audit = document.createElement('a');
    audit.href = '/admin/audit-logs';
    audit.id = 'nav-admin-audit';
    audit.className = 'nav-item';
    audit.innerHTML = '<span class="nav-icon">&#9998;</span> Auditoria';
    const smtp = document.createElement('a');
    smtp.href = '/admin/smtp';
    smtp.id = 'nav-admin-smtp';
    smtp.className = 'nav-item';
    smtp.innerHTML = '<span class="nav-icon">&#9993;</span> Email automatico';
    nav.insertBefore(users, document.getElementById('nav-alerts'));
    nav.insertBefore(depts, document.getElementById('nav-alerts'));
    nav.insertBefore(smtp, document.getElementById('nav-alerts'));
    nav.insertBefore(audit, document.getElementById('nav-alerts'));
  }
  if (['MANAGER', 'DIRECTOR'].includes(role) && !document.getElementById('nav-approval-queue')) {
    const href = role === 'MANAGER' ? '/manager/queue' : '/director/queue';
    const item = document.createElement('a');
    item.href = href;
    item.id = 'nav-approval-queue';
    item.className = 'nav-item';
    item.innerHTML = '<span class="nav-icon">&#8801;</span> Fila de Aprovacao <span class="badge-count hidden" id="queue-count-nav"></span>';
    nav.insertBefore(item, document.getElementById('nav-alerts'));
  }
  if (role === 'FINANCE' && !document.getElementById('nav-finance-queue')) {
    const queue = document.createElement('a');
    queue.href = '/finance/queue';
    queue.id = 'nav-finance-queue';
    queue.className = 'nav-item';
    queue.innerHTML = '<span class="nav-icon">&#9724;</span> Lancamentos <span class="badge-count hidden" id="finance-count-nav"></span>';
    nav.insertBefore(queue, document.getElementById('nav-alerts'));
    // Historico foi fundido na pagina /invoices (que ja tem totalizer + filtros completos)
  }
}

async function initDashboard() {
  const user = Auth.getUser();
  const hour = hourInBR();
  const greeting = hour < 12 ? 'Bom dia' : hour < 18 ? 'Boa tarde' : 'Boa noite';
  document.getElementById('dashboard-greeting').textContent = `${greeting}, ${user.name}`;

  try {
    const [invoicesData, alertsData] = await Promise.all([
      apiFetch('/api/invoices/?per_page=5'),
      apiFetch('/alerts/')
    ]);
    renderStats(alertsData.summary);
    renderAlerts(alertsData);
    renderRecentInvoices(invoicesData.items);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function renderStats(summary) {
  const grid = document.getElementById('stats-grid');
  const cards = [
    { label: 'Pendentes revisao', value: summary.pending_review_count, color: 'blue', icon: '...' },
    { label: 'Vencem em 72h', value: summary.due_72h_count, color: 'warning', icon: '!' },
    { label: 'Vencidas', value: summary.overdue_count, color: 'error', icon: 'x' },
    { label: 'Emissao antiga', value: summary.old_emission_count, color: 'muted', icon: '#' }
  ];
  grid.innerHTML = cards.map((card) => `
    <div class="stat-card stat-${card.color}">
      <div class="stat-icon">${card.icon}</div>
      <div class="stat-value">${card.value}</div>
      <div class="stat-label">${card.label}</div>
    </div>
  `).join('');
}

function renderAlerts(data) {
  const section = document.getElementById('alerts-section');
  const groups = [
    { key: 'overdue', label: 'Notas vencidas', type: 'error' },
    { key: 'due_72h', label: 'Vencem em menos de 72 horas', type: 'warning' },
    { key: 'old_emission', label: 'Emissao do mes anterior', type: 'info' },
    { key: 'pending_review', label: 'Aguardando sua revisao', type: 'info' }
  ];
  let html = '';
  for (const group of groups) {
    if (!data[group.key]?.length) continue;
    html += `<div class="alert-banner alert-${group.type}">
      <strong>${group.label} (${data[group.key].length})</strong>
      <ul>${data[group.key].slice(0, 3).map((item) =>
        `<li><a href="/invoices/${escapeHtml(item.id)}">${escapeHtml(item.invoice_number)}</a> - ${formatCurrency(item.amount)} - vence ${formatDate(item.due_date)}</li>`
      ).join('')}
      ${data[group.key].length > 3 ? '<li><a href="/alerts">Ver todos...</a></li>' : ''}
      </ul>
    </div>`;
  }
  section.innerHTML = html || '<p class="text-muted">Nenhum alerta no momento.</p>';
}

function renderRecentInvoices(items) {
  const el = document.getElementById('recent-invoices');
  if (!items.length) {
    el.innerHTML = '<p class="text-muted">Nenhuma nota encontrada.</p>';
    return;
  }
  el.innerHTML = `<table class="table">
    <thead><tr>
      <th>Numero</th><th>Valor</th><th>Vencimento</th><th>Status</th><th></th>
    </tr></thead>
    <tbody>${items.map((item) => `<tr>
      <td>${escapeHtml(item.invoice_number)}</td>
      <td>${formatCurrency(item.amount)}</td>
      <td>${formatDate(item.due_date)}</td>
      <td>${statusBadge(item.status)}</td>
      <td><button class="btn btn-ghost btn-sm" data-drawer="${escapeHtml(item.id)}">Ver</button></td>
    </tr>`).join('')}</tbody>
  </table>`;
}

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

async function initConfiguracoes() {
  const user = Auth.getUser();
  if (!user) return;
  const card = document.getElementById('config-availability-card');
  // So MANAGER e DIRECTOR podem pausar recebimento
  if (!['MANAGER', 'DIRECTOR'].includes(user.role)) {
    return;  // card fica oculto pra outros perfis
  }
  card.classList.remove('hidden');

  // Le estado atual via /auth/me (mais fresh que cache)
  const me = await apiFetch('/auth/me');
  const toggle = document.getElementById('config-unavailable-toggle');
  toggle.checked = Boolean(me.unavailable_for_notes);
  document.getElementById('config-availability-status')
    .classList.toggle('hidden', !me.unavailable_for_notes);

  toggle.addEventListener('change', async () => {
    try {
      const resp = await apiFetch('/auth/me/availability', {
        method: 'PUT',
        body: JSON.stringify({ unavailable: toggle.checked }),
      });
      showToast(resp.message, 'success');
      document.getElementById('config-availability-status')
        .classList.toggle('hidden', !toggle.checked);
      // Atualiza cache local para banner global aparecer/sumir
      Auth.setUser({ ...user, unavailable_for_notes: toggle.checked });
      renderGlobalAvailabilityBanner();
    } catch (e) {
      toggle.checked = !toggle.checked;  // reverte UI
      showToast(e.message, 'error');
    }
  });
}

function renderGlobalAvailabilityBanner() {
  // Banner amarelo no topo do conteudo quando o usuario marcou indisponivel
  const user = Auth.getUser();
  const content = document.querySelector('.content');
  if (!content) return;
  let banner = document.getElementById('global-availability-banner');
  if (user?.unavailable_for_notes) {
    if (!banner) {
      banner = document.createElement('div');
      banner.id = 'global-availability-banner';
      banner.className = 'alert-banner alert-warning';
      banner.style.marginBottom = '1rem';
      banner.innerHTML =
        '<strong>Voce esta indisponivel para receber novas notas.</strong> ' +
        '<a href="/configuracoes" style="color:inherit;text-decoration:underline">Reativar</a>';
      content.prepend(banner);
    }
  } else if (banner) {
    banner.remove();
  }
}

function initChangePasswordPage() {
  if (!Auth.getToken()) {
    window.location.href = '/login';
    return;
  }
  // Banner so se forcado. Bloqueio de navegacao tambem so se forcado —
  // troca voluntaria nao deve prender o usuario na pagina.
  const user = Auth.getUser();
  const isForced = Boolean(user?.must_change_password);
  if (isForced) {
    document.getElementById('force-change-banner')?.classList.remove('hidden');
  }
  let changed = false;
  // So bloqueia navegacao se a troca foi FORCADA (admin resetou ou e primeiro
  // login). Troca voluntaria deve permitir cancelar.
  if (isForced) {
    document.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', (event) => {
        if (!changed) event.preventDefault();
      });
    });
  }
  window.addEventListener('beforeunload', (event) => {
    if (!changed && isForced) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
  document.getElementById('change-password-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorEl = document.getElementById('change-password-error');
    const currentPassword = document.getElementById('current-password').value;
    const newPassword = document.getElementById('new-password').value;
    const confirmPassword = document.getElementById('confirm-password').value;
    errorEl.classList.add('hidden');
    if (!validatePassword(newPassword)) {
      errorEl.textContent = 'A nova senha deve ter minimo 8 caracteres, com letra e numero.';
      errorEl.classList.remove('hidden');
      return;
    }
    if (newPassword !== confirmPassword) {
      errorEl.textContent = 'A confirmacao nao confere.';
      errorEl.classList.remove('hidden');
      return;
    }
    try {
      await apiFetch('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
      });
      const user = Auth.getUser();
      user.must_change_password = false;
      Auth.setUser(user);
      changed = true;
      window.location.href = '/dashboard';
    } catch (error) {
      errorEl.textContent = error.message;
      errorEl.classList.remove('hidden');
    }
  });
}

let invoiceListState = {
  page: 1,
  perPage: 20,
  pages: 1,
  status: '',
  search: '',
  fromDate: '',
  toDate: '',
  dueFrom: '',
  dueTo: '',
  minAmount: '',
  maxAmount: '',
  createdBy: '',
};
let _invoicesSearchDebounce = null;

async function initInvoicesList() {
  const triggerReload = () => {
    invoiceListState.page = 1;
    loadInvoicesList();
  };
  // Status (filtro principal)
  document.getElementById('status-filter')?.addEventListener('change', (event) => {
    invoiceListState.status = event.target.value;
    triggerReload();
  });
  // Busca textual com debounce de 300ms
  document.getElementById('invoices-search')?.addEventListener('input', (event) => {
    invoiceListState.search = event.target.value;
    clearTimeout(_invoicesSearchDebounce);
    _invoicesSearchDebounce = setTimeout(triggerReload, 300);
  });
  // Filtros avancados (datas, valores, responsavel)
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
  // Mostrar/esconder filtros avancados
  document.getElementById('invoices-toggle-advanced')?.addEventListener('click', () => {
    document.getElementById('invoices-advanced')?.classList.toggle('hidden');
  });
  // Limpar todos os filtros
  document.getElementById('invoices-clear-filters')?.addEventListener('click', () => {
    invoiceListState = { ...invoiceListState, search: '', fromDate: '', toDate: '', dueFrom: '', dueTo: '', minAmount: '', maxAmount: '', createdBy: '', status: '' };
    ['invoices-search', 'invoices-from-date', 'invoices-to-date', 'invoices-due-from', 'invoices-due-to', 'invoices-min-amount', 'invoices-max-amount', 'invoices-created-by'].forEach((id) => {
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
  await loadInvoicesList();
}

async function loadInvoicesList() {
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

  const data = await apiFetch(`/api/invoices/?${params.toString()}`);
  invoiceListState.pages = data.pages || 1;
  document.getElementById('page-indicator').textContent = `Pagina ${data.page} de ${invoiceListState.pages}`;
  document.getElementById('prev-page').disabled = data.page <= 1;
  document.getElementById('next-page').disabled = data.page >= invoiceListState.pages;
  const countEl = document.getElementById('invoices-count');
  if (countEl) {
    countEl.textContent = data.total != null
      ? `${data.total} nota${data.total === 1 ? '' : 's'} encontrada${data.total === 1 ? '' : 's'}`
      : '';
  }
  const totalizerEl = document.getElementById('invoices-totalizer');
  if (totalizerEl) {
    const count = data.total || 0;
    const sum = data.total_amount || 0;
    totalizerEl.textContent = `${count} nota${count === 1 ? '' : 's'} | Valor total: ${formatCurrency(sum)}`;
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
    <thead><tr><th>Numero</th><th>Setor</th><th>Valor</th><th>Emissao</th><th>Vencimento</th><th>Status</th><th>Acoes</th></tr></thead>
    <tbody>${items.map((item) => {
      const canEdit = ['RASCUNHO', 'REPROVADO_GESTOR', 'REPROVADO_DIRETOR'].includes(item.status);
      const isDraft = item.status === 'RASCUNHO';
      const rejected = item.status.startsWith('REPROVADO');
      return `<tr class="${rejected ? 'rejected-row' : ''}">
        <td>${rejected ? '! ' : ''}${escapeHtml(item.invoice_number)}</td>
        <td>${escapeHtml(item.department_name || '-')}</td>
        <td>${formatCurrency(item.amount)}</td>
        <td>${formatDate(item.issue_date)}</td>
        <td>${formatDate(item.due_date)}</td>
        <td>${statusBadge(item.status)}</td>
        <td class="table-actions">
          <button class="btn btn-ghost btn-sm" data-drawer="${escapeHtml(item.id)}">Ver</button>
          ${canEdit ? `<a class="btn btn-ghost btn-sm" href="/invoices/${item.id}/edit">Editar</a>` : ''}
          ${isDraft ? `<button class="btn btn-danger btn-sm" data-action="delete" data-id="${item.id}">Excluir</button>` : ''}
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

function setupInvoiceFileInput() {
  const dropZone = document.getElementById('drop-zone');
  const input = document.getElementById('invoice-file');
  const label = document.getElementById('selected-file-name');
  if (!dropZone || !input) return;
  const updateName = () => { label.textContent = input.files?.[0]?.name || 'Nenhum arquivo selecionado'; };
  ['dragenter', 'dragover'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.add('dragover');
    });
  });
  ['dragleave', 'drop'].forEach((eventName) => {
    dropZone.addEventListener(eventName, (event) => {
      event.preventDefault();
      dropZone.classList.remove('dragover');
    });
  });
  dropZone.addEventListener('drop', (event) => {
    const file = event.dataTransfer.files?.[0];
    if (!file) return;
    if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
      showToast('Selecione um arquivo PDF.', 'error');
      return;
    }
    const transfer = new DataTransfer();
    transfer.items.add(file);
    input.files = transfer.files;
    updateName();
  });
  input.addEventListener('change', updateName);
}

async function initInvoiceForm(mode) {
  const description = document.getElementById('description');
  description?.addEventListener('input', () => {
    document.getElementById('description-count').textContent = description.value.length;
  });
  setupInvoiceFileInput();

  const user = Auth.getUser();
  if (user?.submit_directly_to_director) {
    const dirGroup = document.getElementById('director-select-group');
    if (dirGroup) dirGroup.style.display = '';
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'director-list', 'chosen-director-id');
    } catch {
      const el = document.getElementById('director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }

  if (mode === 'edit') {
    const invoice = await apiFetch(invoiceApiPath(getInvoiceIdFromPath()));
    if (!['RASCUNHO', 'REPROVADO_GESTOR', 'REPROVADO_DIRETOR'].includes(invoice.status)) {
      showToast('Esta nota nao pode ser editada neste status.', 'error');
      window.location.href = `/invoices/${invoice.id}`;
      return;
    }
    fillInvoiceForm(invoice);
    const submitBtn = document.getElementById('invoice-submit-btn');
    if (submitBtn) submitBtn.textContent = 'Salvar e Reenviar';
    document.getElementById('btn-save-draft')?.classList.add('hidden');
  }

  document.getElementById('btn-save-draft')?.addEventListener('click', () => saveInvoice(null, mode, false));
  document.getElementById('invoice-form')?.addEventListener('submit', (event) => saveInvoice(event, mode, true));
}

function fillInvoiceForm(invoice) {
  document.getElementById('invoice-number').value = invoice.invoice_number;
  document.getElementById('amount').value = invoice.amount;
  document.getElementById('issue-date').value = invoice.issue_date;
  document.getElementById('due-date').value = invoice.due_date;
  document.getElementById('description').value = invoice.description;
  document.getElementById('description-count').textContent = invoice.description.length;
  document.getElementById('bank-details').value = invoice.bank_details || '';
  if (invoice.has_attachment) {
    const box = document.getElementById('current-attachment');
    if (box) {
      box.innerHTML = `<strong>PDF atual:</strong> <a href="/api/invoices/${invoice.id}/attachment" target="_blank" rel="noopener">abrir anexo</a>. Selecione outro PDF para substituir.`;
      box.classList.remove('hidden');
    }
  }
}

async function saveInvoice(event, mode, submitNow = true) {
  if (event) event.preventDefault();
  const issueDate = document.getElementById('issue-date').value;
  const dueDate = document.getElementById('due-date').value;
  const description = document.getElementById('description').value.trim();
  const file = document.getElementById('invoice-file').files?.[0];
  if (dueDate < issueDate) return showToast('Vencimento nao pode ser anterior a emissao.', 'error');
  if (description.length < 10) return showToast('Descricao deve ter ao menos 10 caracteres.', 'error');
  if (file && !file.name.toLowerCase().endsWith('.pdf')) return showToast('Selecione um arquivo PDF.', 'error');
  // PDF obrigatorio para novas notas
  if (mode !== 'edit' && !file) return showToast('Anexe o PDF da nota fiscal antes de continuar.', 'error');
  const form = new FormData();
  form.append('invoice_number', document.getElementById('invoice-number').value.trim());
  form.append('amount', document.getElementById('amount').value);
  form.append('issue_date', issueDate);
  form.append('due_date', dueDate);
  form.append('description', description);
  form.append('bank_details', document.getElementById('bank-details').value.trim());
  if (file) form.append('file', file);
  if (mode !== 'edit') {
    form.append('submit_now', submitNow ? 'true' : 'false');
    const directorId = document.getElementById('chosen-director-id')?.value;
    if (directorId) form.append('director_id', directorId);
  }
  showLoading();
  try {
    const invoiceId = getInvoiceIdFromPath();
    const invoice = await apiFetch(mode === 'edit' ? `/api/invoices/${invoiceId}` : '/api/invoices/', {
      method: mode === 'edit' ? 'PATCH' : 'POST',
      body: form
    });
    const msg = mode === 'edit' ? 'Nota atualizada!' : submitNow ? 'Nota criada e enviada!' : 'Rascunho salvo!';
    showToast(msg, 'success');
    window.location.href = `/invoices/${invoice.id}`;
  } catch (error) {
    showToast(error.message, 'error');
  } finally {
    hideLoading();
  }
}

async function initInvoiceDetail() {
  const invoiceId = getInvoiceIdFromPath();
  const invoice = await apiFetch(invoiceApiPath(invoiceId));
  renderInvoiceDetail(invoice);
  if (invoice.has_attachment) loadPdfInline(invoiceId);
}

function renderInvoiceAlerts(invoice, containerId) {
  // Banners contextuais (emissao antiga, vencimento curto).
  // Insere/atualiza dinamicamente acima do container alvo.
  const target = document.getElementById(containerId);
  if (!target) return;
  const alertsId = `${containerId}-alerts-banner`;
  let banner = document.getElementById(alertsId);
  const items = invoice?.alerts || [];
  if (!items.length) {
    if (banner) banner.remove();
    return;
  }
  if (!banner) {
    banner = document.createElement('div');
    banner.id = alertsId;
    banner.className = 'alert-banner alert-warning';
    banner.style.marginBottom = '1rem';
    target.parentNode.insertBefore(banner, target);
  }
  banner.innerHTML = '<strong>Atencao:</strong><ul>' +
    items.map((m) => `<li>${escapeHtml(m)}</li>`).join('') + '</ul>';
}

function renderInvoiceDetail(invoice) {
  document.getElementById('detail-title').textContent = `Nota ${invoice.invoice_number}`;
  document.getElementById('detail-subtitle').textContent = `Criada por ${invoice.created_by.name} em ${formatDateTime(invoice.created_at)}`;
  document.getElementById('detail-status').innerHTML = statusBadge(invoice.status);
  renderInvoiceAlerts(invoice, 'detail-grid');
  document.getElementById('detail-grid').innerHTML = [
    ['Valor', formatCurrency(invoice.amount)], ['Emissao', formatDate(invoice.issue_date)],
    ['Vencimento', formatDate(invoice.due_date)], ['Criador', invoice.created_by.name],
    ['Setor', invoice.department_name || '-'], ['Descricao', invoice.description],
    ['Dados bancarios', invoice.bank_details || '-']
  ].map(([label, value]) => `<div class="detail-item"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`).join('');
  // Reprovacao MAIS RECENTE — se a nota foi reprovada, editada e reprovada de
  // novo, o usuario precisa ver o motivo atual, nao o primeiro.
  const rejection = [...invoice.history].reverse().find((item) => item.action.startsWith('REJECTED'));
  const box = document.getElementById('rejection-box');
  if (box) {
    if (rejection) {
      box.innerHTML = `<strong>Motivo da reprovacao:</strong> ${escapeHtml(rejection.comment || 'Sem comentario.')}`;
      box.classList.remove('hidden');
    } else {
      box.classList.add('hidden');
    }
  }
  renderDetailActions(invoice);
  renderTimeline(invoice.history);
}

async function renderDetailActions(invoice) {
  const actions = document.getElementById('detail-actions');
  if (!actions) return;
  const user = Auth.getUser();
  const isDirect = Boolean(user?.submit_directly_to_director);
  const buttons = [];
  if (invoice.can_cancel) {
    buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
  }
  if (invoice.status === 'RASCUNHO') {
    buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
    if (isDirect) {
      buttons.push('<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>');
    } else {
      buttons.push('<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
    }
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }
  if (invoice.status.startsWith('REPROVADO')) {
    buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
  }
  let directorHtml = '';
  if (invoice.status === 'RASCUNHO' && isDirect) {
    directorHtml = '<div class="form-group" id="detail-director-wrap"><label class="form-label">Enviar para o diretor:</label><div id="detail-director-list" class="director-list"><p class="text-muted">Carregando...</p></div><input type="hidden" id="detail-chosen-director"></div>';
  }
  actions.innerHTML = directorHtml + buttons.join('');
  if (invoice.status === 'RASCUNHO' && isDirect) {
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'detail-director-list', 'detail-chosen-director');
    } catch {
      const el = document.getElementById('detail-director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }
  actions.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', async () => {
      try {
        if (button.dataset.action === 'submit') {
          const updated = await apiFetch(`/api/invoices/${invoice.id}/submit`, { method: 'POST' });
          showToast('Nota enviada para o gestor.', 'success');
          renderInvoiceDetail(updated);
          if (updated.has_attachment) loadPdfInline(updated.id);
        } else if (button.dataset.action === 'submit-direct') {
          const dirId = document.getElementById('detail-chosen-director')?.value;
          if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
          const updated = await apiFetch(`/api/invoices/${invoice.id}/submit?director_id=${encodeURIComponent(dirId)}`, { method: 'POST' });
          showToast('Nota enviada para o diretor.', 'success');
          renderInvoiceDetail(updated);
          if (updated.has_attachment) loadPdfInline(updated.id);
        } else if (button.dataset.action === 'cancel') {
          if (!(await confirmAction('Cancelar esta nota? Ela voltara para rascunho.'))) return;
          const updated = await apiFetch(`/api/invoices/${invoice.id}/cancel`, { method: 'POST' });
          showToast('Nota cancelada.', 'success');
          renderInvoiceDetail(updated);
        } else if (button.dataset.action === 'delete') {
          if (!(await confirmAction('Excluir esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}`, { method: 'DELETE' });
          window.location.href = '/invoices';
        }
      } catch (e) { showToast(e.message, 'error'); }
    });
  });
}

function renderTimeline(history) {
  const icons = { CREATED: '+', SUBMITTED: '>', APPROVED_MANAGER: '✓', REJECTED_MANAGER: 'x', APPROVED_DIRECTOR: '✓', REJECTED_DIRECTOR: 'x', MARKED_PAID: '$' };
  const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Envio cancelado', APPROVED_MANAGER: 'Aprovada pelo gestor', REJECTED_MANAGER: 'Reprovada pelo gestor', APPROVED_DIRECTOR: 'Aprovada pelo diretor', REJECTED_DIRECTOR: 'Reprovada pelo diretor', MARKED_PAID: 'Marcada como lancada', PRINTED: 'Impressa' };
  const el = document.getElementById('invoice-timeline');
  if (!el) return;
  el.innerHTML = history.map((item) => `
    <div class="timeline-item"><div class="timeline-icon">${icons[item.action] || '-'}</div><div>
      <strong>${labels[item.action] || item.action}</strong>
      <div class="timeline-meta">${escapeHtml(item.user.name)} - ${formatDateTime(item.timestamp)}</div>
      ${item.comment ? `<p>${escapeHtml(item.comment)}</p>` : ''}
    </div></div>`).join('');
}

// ── PDF helpers ──────────────────────────────────────────────────────────────

async function fetchAndOpenPdf(url) {
  showLoading();
  try {
    const token = Auth.getToken();
    const resp = await fetch(url, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!resp.ok) {
      let detail = 'Erro ao gerar PDF';
      try { detail = (await resp.json()).detail || detail; } catch {}
      throw new Error(detail);
    }
    const blob = await resp.blob();
    const blobUrl = URL.createObjectURL(blob);
    window.open(blobUrl, '_blank');
    return true;
  } catch (e) {
    showToast(e.message, 'error');
    return false;
  } finally {
    hideLoading();
  }
}

// ── PDF inline + director selection helpers ─────────────────────────────────

async function loadPdfInline(invoiceId) {
  const panel = document.getElementById('pdf-panel');
  if (!panel) return;
  try {
    const token = Auth.getToken();
    const resp = await fetch(`/api/invoices/${invoiceId}/attachment`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const iframe = document.getElementById('pdf-iframe');
    const link = document.getElementById('pdf-download-link');
    if (iframe) iframe.src = url;
    if (link) link.href = url;
    panel.style.display = 'block';
  } catch {}
}

function renderDirectorList(directors, containerId, hiddenInputId) {
  const container = document.getElementById(containerId);
  const hiddenInput = hiddenInputId ? document.getElementById(hiddenInputId) : null;
  if (!container) return;
  if (!directors || !directors.length) {
    container.innerHTML = '<p class="text-muted">Nenhum diretor disponivel.</p>';
    return;
  }
  container.innerHTML = directors.map((d) => `
    <div class="director-card" data-id="${escapeHtml(d.id)}">
      <strong>${escapeHtml(d.name)}</strong>
      ${d.is_primary
        ? '<span class="badge-primary-sector">Responsavel pelo seu setor</span>'
        : '<span class="badge-other-sector">Nao e o diretor padrao deste setor</span>'}
    </div>`).join('');
  const primary = directors.find((d) => d.is_primary) || directors[0];
  if (primary && hiddenInput) {
    hiddenInput.value = primary.id;
    container.querySelector(`[data-id="${primary.id}"]`)?.classList.add('selected');
  }
  container.querySelectorAll('.director-card').forEach((card) => {
    card.addEventListener('click', () => {
      container.querySelectorAll('.director-card').forEach((c) => c.classList.remove('selected'));
      card.classList.add('selected');
      if (hiddenInput) hiddenInput.value = card.dataset.id;
    });
  });
}

function pickDirectorModal(directors) {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal modal-wide">
        <h2>Encaminhar para diretor</h2>
        <p class="text-muted">Selecione o diretor responsavel pela aprovacao desta nota.</p>
        <div id="pick-director-list" class="director-list"></div>
        <input type="hidden" id="pick-director-id">
        <div class="modal-actions">
          <button class="btn btn-ghost" data-action="cancel">Cancelar</button>
          <button class="btn btn-primary" data-action="confirm">Encaminhar</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    renderDirectorList(directors, 'pick-director-list', 'pick-director-id');
    backdrop.addEventListener('click', (event) => {
      const action = event.target.closest('[data-action]')?.dataset.action;
      if (!action) return;
      const dirId = document.getElementById('pick-director-id')?.value;
      backdrop.remove();
      resolve(action === 'confirm' && dirId ? dirId : null);
    });
  });
}

// ── Alerts ──────────────────────────────────────────────────────────────────

async function initAlertsPage() {
  const data = await apiFetch('/alerts/');
  const groups = [['overdue', 'Vencidas', 'error'], ['due_72h', 'Vencem em 72h', 'warning'], ['old_emission', 'Emissao antiga', 'info'], ['pending_review', 'Aguardando revisao', 'info']];
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
  return `<table class="table"><thead><tr><th>Numero</th><th>Valor</th><th>Emissao</th><th>Vencimento</th><th>Status</th><th></th></tr></thead>
    <tbody>${items.map((item) => `<tr><td>${escapeHtml(item.invoice_number)}</td><td>${formatCurrency(item.amount)}</td><td>${formatDate(item.issue_date)}</td><td>${formatDate(item.due_date)}</td><td>${statusBadge(item.status)}</td><td><button class="btn btn-ghost btn-sm" data-drawer="${escapeHtml(item.id)}">Ver</button></td></tr>`).join('')}</tbody></table>`;
}

function isWithinDateRange(dateStr, from, to) {
  if (from && dateStr < from) return false;
  if (to && dateStr > to) return false;
  return true;
}

// ── Finance ──────────────────────────────────────────────────────────────────

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
    state.dueFrom = '';
    state.dueTo = '';
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
  el.innerHTML = `<table class="table"><thead><tr>
    <th>Numero</th><th>Criado por</th><th>Valor</th><th>Vencimento</th><th>Status</th><th>Acoes</th>
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

  // Monta timeline de aprovacao financeira
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

  // Nota ja lancada
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

  // Nota aprovada — pronta para impressao e lancamento
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

  document.getElementById('print-invoice-btn')?.addEventListener('click', async () => {
    const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/print`);
    if (ok) {
      showToast('Comprovante gerado. Recebimento registrado no sistema.', 'success');
      setTimeout(() => window.location.reload(), 1800);
    }
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

// ── Review (manager / director) ──────────────────────────────────────────────

async function reviewInvoice(invoiceId, action, endpoint, directorId = null) {
  let comment = null;
  if (action === 'APPROVE') {
    // Sem confirmacao dupla pra aprovacao — usuario ja clicou no botao
    // explicito 'Aprovar'. Reprovacao continua exigindo motivo (modal abaixo).
  } else {
    comment = await rejectReasonModal();
    if (!comment) return false;
  }
  try {
    const body = { action, comment };
    if (directorId) body.director_id = directorId;
    await apiFetch(endpoint, {
      method: 'POST',
      body: JSON.stringify(body)
    });
    showToast(action === 'APPROVE' ? 'Nota aprovada com sucesso.' : 'Nota reprovada com sucesso.', 'success');
    return true;
  } catch (error) {
    showToast(error.message, 'error');
    return false;
  }
}

async function initReviewQueue(role) {
  const state = { mode: 'pending' };
  const statusFilter = role === 'manager' ? 'AGUARDANDO_GESTOR' : 'AGUARDANDO_DIRETOR';
  const containerId = role === 'manager' ? 'manager-queue-table' : 'director-queue-table';
  const endpointPart = role === 'manager' ? 'review' : 'director-review';
  const detailPrefix = role === 'manager' ? '/manager/invoices' : '/director/invoices';
  const filter = document.getElementById(`${role}-queue-filter`);
  filter?.querySelectorAll('button').forEach((button) => {
    button.addEventListener('click', () => {
      filter.querySelectorAll('button').forEach((item) => item.classList.remove('active'));
      button.classList.add('active');
      state.mode = button.dataset.mode;
      loadReviewQueue();
    });
  });

  async function loadReviewQueue() {
    const url = state.mode === 'pending' ? `/api/invoices/?status=${statusFilter}&per_page=100` : '/api/invoices/?per_page=100';
    const data = await apiFetch(url);
    const pendingCount = data.items.filter((item) => item.status === statusFilter).length;
    document.getElementById('queue-count').textContent = `${pendingCount} pendentes`;
    const navCount = document.getElementById('queue-count-nav');
    if (navCount) {
      navCount.textContent = pendingCount;
      navCount.classList.toggle('hidden', pendingCount === 0);
    }
    renderReviewQueue(data.items);
  }

  function renderReviewQueue(items) {
    const container = document.getElementById(containerId);
    if (!items.length) {
      container.innerHTML = '<div class="alert-banner alert-info"><strong>Nenhuma nota aguardando aprovacao.</strong></div>';
      return;
    }
    const directorExtraHead = role === 'director' ? '<th>Gestor</th><th>Aprovado pelo Gestor em</th>' : '';
    container.innerHTML = `<table class="table"><thead><tr>
      <th>Funcionario</th><th>Setor</th><th>Numero da nota</th><th>Valor</th><th>Emissao</th><th>Vencimento</th><th>Dias ate vencer</th>${directorExtraHead}<th>Acoes</th>
    </tr></thead><tbody>${items.map((item) => {
      const canReview = item.status === statusFilter;
      const directorExtra = role === 'director' ? `<td>${escapeHtml(item.manager?.name || '-')}</td><td>${formatDateTime(item.manager_reviewed_at)}</td>` : '';
      return `<tr>
        <td>${escapeHtml(item.created_by.name)}</td>
        <td>${escapeHtml(item.department_name || '-')}</td>
        <td>${escapeHtml(item.invoice_number)}</td>
        <td>${formatCurrency(item.amount)}</td>
        <td>${formatDate(item.issue_date)}</td>
        <td>${formatDate(item.due_date)}</td>
        <td>${daysBadge(item.due_date)}</td>
        ${directorExtra}
        <td class="table-actions">
          <button class="btn btn-ghost btn-sm" data-drawer="${item.id}">Ver</button>
          ${canReview ? `<button class="btn btn-secondary btn-sm" data-action="APPROVE" data-id="${item.id}">Aprovar</button><button class="btn btn-danger btn-sm" data-action="REJECT" data-id="${item.id}">Reprovar</button>` : statusBadge(item.status)}
        </td>
      </tr>`;
    }).join('')}</tbody></table>`;
    container.querySelectorAll('button[data-action]').forEach((button) => {
      button.addEventListener('click', async () => {
        if (role === 'manager' && button.dataset.action === 'APPROVE') {
          let directors = [];
          try { directors = await apiFetch('/api/invoices/directors'); } catch {}
          const directorId = await pickDirectorModal(directors);
          if (!directorId) return;
          const ok = await reviewInvoice(button.dataset.id, 'APPROVE', `/api/invoices/${button.dataset.id}/${endpointPart}`, directorId);
          if (ok) await loadReviewQueue();
        } else {
          const ok = await reviewInvoice(button.dataset.id, button.dataset.action, `/api/invoices/${button.dataset.id}/${endpointPart}`);
          if (ok) await loadReviewQueue();
        }
      });
    });
  }
  await loadReviewQueue();
}

async function initReviewDetail(role) {
  const invoiceId = getInvoiceIdFromPath();
  const invoice = await apiFetch(invoiceApiPath(invoiceId));
  renderInvoiceDetail(invoice);
  if (invoice.has_attachment) loadPdfInline(invoiceId);

  const statusNeeded = role === 'manager' ? 'AGUARDANDO_GESTOR' : 'AGUARDANDO_DIRETOR';
  if (invoice.status !== statusNeeded) return;

  const panel = document.getElementById('review-panel');
  if (!panel) return;
  panel.classList.remove('hidden');

  if (role === 'manager') {
    try {
      const directors = await apiFetch('/api/invoices/directors');
      renderDirectorList(directors, 'director-list', 'chosen-director-id');
    } catch {
      const el = document.getElementById('director-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
    document.getElementById('btn-approve')?.addEventListener('click', async () => {
      const dirId = document.getElementById('chosen-director-id')?.value;
      if (!dirId) { showToast('Selecione um diretor para encaminhar a nota.', 'error'); return; }
      try {
        await apiFetch(`/api/invoices/${invoiceId}/review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'APPROVE', director_id: dirId })
        });
        showToast('Nota aprovada e encaminhada ao diretor.', 'success');
        window.location.reload();
      } catch (e) { showToast(e.message, 'error'); }
    });
  } else {
    document.getElementById('btn-approve')?.addEventListener('click', async () => {
      try {
        await apiFetch(`/api/invoices/${invoiceId}/director-review`, {
          method: 'POST',
          body: JSON.stringify({ action: 'APPROVE' })
        });
        showToast('Nota aprovada com sucesso.', 'success');
        window.location.reload();
      } catch (e) { showToast(e.message, 'error'); }
    });
  }

  const endpoint = role === 'manager' ? 'review' : 'director-review';
  document.getElementById('btn-show-reject')?.addEventListener('click', () => {
    document.getElementById('reject-section')?.classList.remove('hidden');
    document.getElementById('btn-approve')?.setAttribute('disabled', '');
    document.getElementById('btn-show-reject')?.setAttribute('disabled', '');
  });
  document.getElementById('btn-cancel-reject')?.addEventListener('click', () => {
    document.getElementById('reject-section')?.classList.add('hidden');
    document.getElementById('btn-approve')?.removeAttribute('disabled');
    document.getElementById('btn-show-reject')?.removeAttribute('disabled');
  });
  const rejectComment = document.getElementById('reject-comment');
  const confirmBtn = document.getElementById('btn-confirm-reject');
  rejectComment?.addEventListener('input', () => {
    if (confirmBtn) confirmBtn.disabled = rejectComment.value.trim().length < 10;
  });
  confirmBtn?.addEventListener('click', async () => {
    try {
      await apiFetch(`/api/invoices/${invoiceId}/${endpoint}`, {
        method: 'POST',
        body: JSON.stringify({ action: 'REJECT', comment: rejectComment.value.trim() })
      });
      showToast('Nota reprovada.', 'success');
      window.location.reload();
    } catch (e) { showToast(e.message, 'error'); }
  });
}

// ── Admin helpers ────────────────────────────────────────────────────────────

const adminRoleLabels = { ...ROLE_LABELS, ADMIN: 'Admin', FINANCE: 'Financeiro' };

let adminUsersCache = [];
let adminAuditState = { page: 1, pages: 1, filters: {} };

function adminRoleBadge(role) {
  return `<span class="role-chip role-${String(role).toLowerCase()}">${adminRoleLabels[role] || role}</span>`;
}

function adminUserStatus(user) {
  if (!user.is_active) return '<span class="status-badge user-status-inactive">Inativo</span>';
  if (user.blocked_until && new Date(user.blocked_until) > new Date()) {
    return '<span class="status-badge user-status-blocked">Bloqueado</span>';
  }
  return '<span class="status-badge user-status-active">Ativo</span>';
}

async function adminLoadManagers(selectId, selectedId = '') {
  const select = document.getElementById(selectId);
  if (!select) return;
  const managers = await apiFetch('/api/admin/managers');
  select.innerHTML = '<option value="">Sem gestor</option>';
  managers.forEach((manager) => {
    const option = document.createElement('option');
    option.value = manager.id;
    option.textContent = manager.name;
    option.selected = manager.id === selectedId;
    select.appendChild(option);
  });
}

async function adminLoadDepartments(selectId, selectedId = '') {
  const select = document.getElementById(selectId);
  if (!select) return;
  try {
    const depts = await apiFetch('/api/admin/departments');
    select.innerHTML = '<option value="">Sem departamento</option>';
    depts.forEach((dept) => {
      const option = document.createElement('option');
      option.value = dept.id;
      option.textContent = dept.name;
      option.selected = dept.id === selectedId;
      select.appendChild(option);
    });
  } catch {
    select.innerHTML = '<option value="">Erro ao carregar departamentos</option>';
  }
}

function adminToggleManagerField(roleId, fieldId) {
  const role = document.getElementById(roleId)?.value;
  document.getElementById(fieldId)?.classList.toggle('hidden', role !== 'EMPLOYEE');
}

async function initAdminUsers() {
  document.getElementById('admin-edit-cancel')?.addEventListener('click', () => {
    document.getElementById('admin-edit-modal').classList.add('hidden');
  });
  document.getElementById('admin-reset-cancel')?.addEventListener('click', () => {
    document.getElementById('admin-reset-modal').classList.add('hidden');
  });
  document.getElementById('admin-edit-role')?.addEventListener('change', () => {
    adminToggleManagerField('admin-edit-role', 'admin-edit-manager-field');
  });
  document.getElementById('admin-edit-form')?.addEventListener('submit', saveAdminEdit);
  document.getElementById('admin-reset-form')?.addEventListener('submit', resetAdminPassword);
  // Filtros instantaneos
  document.getElementById('admin-users-search')?.addEventListener('input', applyAdminUsersFilter);
  document.getElementById('admin-users-role-filter')?.addEventListener('change', applyAdminUsersFilter);
  document.getElementById('admin-users-status-filter')?.addEventListener('change', applyAdminUsersFilter);
  await adminLoadManagers('admin-edit-manager');
  await loadAdminUsers();
}

async function loadAdminUsers() {
  try {
    adminUsersCache = await apiFetch('/api/admin/users');
    applyAdminUsersFilter();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function applyAdminUsersFilter() {
  const term = (document.getElementById('admin-users-search')?.value || '').trim().toLowerCase();
  const roleFilter = document.getElementById('admin-users-role-filter')?.value || '';
  const statusFilter = document.getElementById('admin-users-status-filter')?.value || '';

  const filtered = (adminUsersCache || []).filter((user) => {
    // Busca textual livre — bate em qualquer um destes campos
    if (term) {
      const haystack = [
        user.name,
        user.email,
        user.role,
        user.department_name,
        user.id,
      ].filter(Boolean).join(' ').toLowerCase();
      if (!haystack.includes(term)) return false;
    }
    // Filtro de perfil
    if (roleFilter && user.role !== roleFilter) return false;
    // Filtro de status
    if (statusFilter) {
      const blocked = user.blocked_until && new Date(user.blocked_until) > new Date();
      if (statusFilter === 'active' && (!user.is_active || blocked)) return false;
      if (statusFilter === 'inactive' && user.is_active) return false;
      if (statusFilter === 'blocked' && !blocked) return false;
    }
    return true;
  });

  const countEl = document.getElementById('admin-users-count');
  if (countEl) {
    const total = (adminUsersCache || []).length;
    countEl.textContent = filtered.length === total
      ? `${total} usuario${total === 1 ? '' : 's'}`
      : `${filtered.length} de ${total}`;
  }

  renderAdminUsersTable(filtered);
}

function renderAdminUsersTable(users) {
  const tbody = document.getElementById('admin-users-tbody');
  if (!tbody) return;
  if (!users.length) {
    const total = (adminUsersCache || []).length;
    const msg = total === 0
      ? 'Nenhum usuario cadastrado.'
      : 'Nenhum usuario corresponde aos filtros aplicados.';
    tbody.innerHTML = `<tr><td colspan="7" class="text-muted">${msg}</td></tr>`;
    return;
  }
  const me = Auth.getUser();
  tbody.innerHTML = users.map((user) => {
    const blocked = user.blocked_until && new Date(user.blocked_until) > new Date();
    const isAdmin = user.role === 'ADMIN';
    const isSelf = user.id === me?.id;
    // ADMINs: só redefinir senha e editar completo (sem toggle ativo/inativo, sem remover)
    const toggleBtn = (!isAdmin && !isSelf)
      ? `<button class="btn ${user.is_active ? 'btn-ghost' : 'btn-secondary'} btn-sm" data-action="toggle" data-id="${user.id}" data-active="${user.is_active}">${user.is_active ? 'Desativar' : 'Ativar'}</button>`
      : '';
    const unlockBtn = (blocked && !isAdmin)
      ? `<button class="btn btn-ghost btn-sm" data-action="unlock" data-id="${user.id}">Desbloquear</button>`
      : '';
    return `<tr${isAdmin ? ' class="row-admin"' : ''}>
      <td>${escapeHtml(user.name)}${isSelf ? ' <span class="badge-self">voce</span>' : ''}</td>
      <td>${escapeHtml(user.email)}</td>
      <td>${adminRoleBadge(user.role)}</td>
      <td>${escapeHtml(user.department_name || '-')}</td>
      <td>${adminUserStatus(user)}</td>
      <td>${formatDateTime(user.last_login)}</td>
      <td class="table-actions">
        <a class="btn btn-ghost btn-sm" href="/admin/users/${user.id}/edit">Editar</a>
        <button class="btn btn-ghost btn-sm" data-action="quick-edit" data-id="${user.id}">Editar rapido</button>
        <button class="btn btn-ghost btn-sm" data-action="reset" data-id="${user.id}">Redefinir senha</button>
        ${unlockBtn}${toggleBtn}
      </td>
    </tr>`;
  }).join('');
  tbody.querySelectorAll('button[data-action]').forEach((button) => {
    button.addEventListener('click', () => handleAdminUserAction(button));
  });
}

async function handleAdminUserAction(button) {
  const { action, id } = button.dataset;
  if (action === 'quick-edit') await openAdminEditModal(id);
  if (action === 'reset') openAdminResetModal(id);
  if (action === 'unlock') await unlockAdminUser(id);
  if (action === 'toggle') await toggleAdminUserActive(id, button.dataset.active === 'true');
}

async function openAdminEditModal(userId) {
  try {
    const user = await apiFetch(`/api/admin/users/${userId}`);
    document.getElementById('admin-edit-user-id').value = user.id;
    document.getElementById('admin-edit-name').value = user.name;
    document.getElementById('admin-edit-role').value = user.role;
    document.getElementById('admin-edit-must-change').checked = Boolean(user.must_change_password);
    document.getElementById('admin-edit-submit-directly').checked = Boolean(user.submit_directly_to_director);
    await adminLoadDepartments('admin-edit-dept-id', user.department_id || '');
    await adminLoadManagers('admin-edit-manager', user.manager_id || '');
    adminToggleManagerField('admin-edit-role', 'admin-edit-manager-field');
    document.getElementById('admin-edit-modal').classList.remove('hidden');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveAdminEdit(event) {
  event.preventDefault();
  const userId = document.getElementById('admin-edit-user-id').value;
  const role = document.getElementById('admin-edit-role').value;
  const payload = {
    name: document.getElementById('admin-edit-name').value.trim(),
    department_id: document.getElementById('admin-edit-dept-id').value || null,
    submit_directly_to_director: document.getElementById('admin-edit-submit-directly').checked,
    role,
    manager_id: role === 'EMPLOYEE' ? document.getElementById('admin-edit-manager').value : '',
    must_change_password: document.getElementById('admin-edit-must-change').checked
  };
  try {
    await apiFetch(`/api/admin/users/${userId}`, { method: 'PUT', body: JSON.stringify(payload) });
    document.getElementById('admin-edit-modal').classList.add('hidden');
    showToast('Usuario atualizado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

function openAdminResetModal(userId) {
  const user = adminUsersCache.find((item) => item.id === userId);
  document.getElementById('admin-reset-user-id').value = userId;
  document.getElementById('admin-reset-password').value = '';
  document.getElementById('admin-reset-user-label').textContent = user ? user.email : '';
  document.getElementById('admin-reset-modal').classList.remove('hidden');
}

async function resetAdminPassword(event) {
  event.preventDefault();
  const userId = document.getElementById('admin-reset-user-id').value;
  const newPassword = document.getElementById('admin-reset-password').value;
  try {
    await apiFetch(`/api/admin/users/${userId}/reset-password`, {
      method: 'POST',
      body: JSON.stringify({ new_password: newPassword })
    });
    document.getElementById('admin-reset-modal').classList.add('hidden');
    showToast('Senha redefinida.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function unlockAdminUser(userId) {
  try {
    await apiFetch(`/api/admin/users/${userId}/unlock`, { method: 'POST' });
    showToast('Usuario desbloqueado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function toggleAdminUserActive(userId, currentActive) {
  if (!(await confirmAction(currentActive ? 'Desativar este usuario?' : 'Ativar este usuario?'))) return;
  try {
    await apiFetch(`/api/admin/users/${userId}`, {
      method: 'PUT',
      body: JSON.stringify({ is_active: !currentActive })
    });
    showToast(currentActive ? 'Usuario desativado.' : 'Usuario ativado.', 'success');
    await loadAdminUsers();
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function initAdminUserForm() {
  const page = document.getElementById('admin-user-form-page');
  const mode = page.dataset.mode;
  const userId = page.dataset.userId;
  document.getElementById('admin-user-role')?.addEventListener('change', () => {
    adminToggleManagerField('admin-user-role', 'admin-manager-field');
  });
  await adminLoadManagers('admin-user-manager');
  await adminLoadDepartments('admin-user-dept-id');
  if (mode === 'edit') {
    document.getElementById('admin-user-email').disabled = true;
    document.getElementById('admin-password-field').classList.add('hidden');
    await loadAdminUserFormData(userId);
  }
  adminToggleManagerField('admin-user-role', 'admin-manager-field');
  document.getElementById('admin-user-form')?.addEventListener('submit', saveAdminUserForm);
}

async function loadAdminUserFormData(userId) {
  try {
    const user = await apiFetch(`/api/admin/users/${userId}`);
    document.getElementById('admin-user-name').value = user.name;
    document.getElementById('admin-user-email').value = user.email;
    document.getElementById('admin-user-role').value = user.role;
    document.getElementById('admin-user-must-change').checked = Boolean(user.must_change_password);
    document.getElementById('admin-user-submit-directly').checked = Boolean(user.submit_directly_to_director);
    await adminLoadDepartments('admin-user-dept-id', user.department_id || '');
    await adminLoadManagers('admin-user-manager', user.manager_id || '');
    adminToggleManagerField('admin-user-role', 'admin-manager-field');
  } catch (error) {
    showToast(error.message, 'error');
  }
}

async function saveAdminUserForm(event) {
  event.preventDefault();
  const page = document.getElementById('admin-user-form-page');
  const mode = page.dataset.mode;
  const userId = page.dataset.userId;
  const role = document.getElementById('admin-user-role').value;
  const departmentId = document.getElementById('admin-user-dept-id').value || null;
  const submitDirectly = document.getElementById('admin-user-submit-directly').checked;
  const managerId = document.getElementById('admin-user-manager').value || '';

  // Validacoes client-side espelhando as do backend pra dar feedback imediato
  if (role !== 'ADMIN' && !departmentId) {
    showToast('Selecione um setor para este perfil.', 'error');
    return;
  }
  if (role === 'EMPLOYEE' && !managerId && !submitDirectly) {
    showToast('Funcionario precisa de gestor ou da opcao "envia direto ao diretor".', 'error');
    return;
  }

  const payload = {
    name: document.getElementById('admin-user-name').value.trim(),
    role,
    department_id: departmentId,
    submit_directly_to_director: submitDirectly,
    manager_id: role === 'EMPLOYEE' ? managerId : '',
    must_change_password: document.getElementById('admin-user-must-change').checked
  };
  if (mode === 'create') {
    payload.email = document.getElementById('admin-user-email').value.trim();
    payload.password = document.getElementById('admin-user-password').value;
    if (payload.password.length < 8) {
      showToast('Senha deve ter no minimo 8 caracteres.', 'error');
      return;
    }
  }
  try {
    const url = mode === 'create' ? '/api/admin/users' : `/api/admin/users/${userId}`;
    const method = mode === 'create' ? 'POST' : 'PUT';
    await apiFetch(url, { method, body: JSON.stringify(payload) });
    showToast(mode === 'create' ? 'Usuario criado com sucesso!' : 'Alteracoes salvas.', 'success');
    setTimeout(() => { window.location.href = '/admin/users'; }, 1500);
  } catch (error) {
    showToast(error.message, 'error');
  }
}

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
  } catch (error) {
    showToast(error.message, 'error');
  }
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
  } catch (error) {
    showToast(error.message, 'error');
  }
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

function rejectReasonModal() {
  return new Promise((resolve) => {
    const backdrop = document.createElement('div');
    backdrop.className = 'modal-backdrop';
    backdrop.innerHTML = `
      <div class="modal">
        <h2>Reprovar nota</h2>
        <p class="text-muted">Informe o motivo da reprovacao.</p>
        <textarea class="form-input review-modal-field" id="reject-reason" minlength="10" maxlength="1000" placeholder="Motivo com no minimo 10 caracteres"></textarea>
        <div class="modal-actions">
          <button class="btn btn-ghost" data-action="cancel">Cancelar</button>
          <button class="btn btn-danger" data-action="confirm" disabled>Reprovar</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    const textarea = backdrop.querySelector('#reject-reason');
    const confirm = backdrop.querySelector('[data-action="confirm"]');
    textarea.addEventListener('input', () => { confirm.disabled = textarea.value.trim().length < 10; });
    backdrop.addEventListener('click', (event) => {
      const action = event.target.dataset.action;
      if (!action) return;
      const value = textarea.value.trim();
      backdrop.remove();
      resolve(action === 'confirm' && value.length >= 10 ? value : null);
    });
    textarea.focus();
  });
}

// ── Invoice Drawer ────────────────────────────────────────────────────────────
// Drawer lateral — abre nota com PDF + ações sem mudar de página

let _drawerEl = null;
let _drawerBackdrop = null;

function _ensureDrawer() {
  if (_drawerEl) return;

  _drawerBackdrop = document.createElement('div');
  _drawerBackdrop.className = 'drawer-backdrop';
  _drawerBackdrop.addEventListener('click', closeDrawer);
  document.body.appendChild(_drawerBackdrop);

  _drawerEl = document.createElement('div');
  _drawerEl.className = 'invoice-drawer';
  _drawerEl.innerHTML = `
    <div class="drawer-header">
      <button class="btn btn-ghost btn-sm" id="drawer-close">&#8592; Fechar</button>
      <div class="drawer-header-info">
        <h2 id="drawer-title">Carregando...</h2>
        <p class="text-muted" id="drawer-subtitle"></p>
      </div>
      <div class="drawer-header-right">
        <div id="drawer-status"></div>
        <a id="drawer-open-page" class="btn btn-ghost btn-sm" style="display:none">Abrir pagina</a>
      </div>
    </div>
    <div class="drawer-body">
      <div id="drawer-rejection-box" class="alert-banner alert-error hidden"></div>
      <div id="drawer-review-panel" class="review-panel card hidden"></div>
      <div id="drawer-actions" class="action-row"></div>
      <div class="detail-layout">
        <div class="detail-left">
          <div class="detail-grid" id="drawer-grid"></div>
          <div class="section-header"><h2>Timeline</h2></div>
          <div class="timeline" id="drawer-timeline"></div>
        </div>
        <div class="detail-right" id="drawer-pdf-panel" style="display:none">
          <div class="pdf-panel-header">
            <span>Documento PDF</span>
            <a id="drawer-pdf-link" class="btn btn-ghost btn-sm" target="_blank">Abrir em nova aba</a>
          </div>
          <iframe id="drawer-pdf-iframe" class="pdf-iframe" title="PDF da nota"></iframe>
        </div>
      </div>
    </div>`;
  document.body.appendChild(_drawerEl);
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
}

function closeDrawer() {
  _drawerEl?.classList.remove('open');
  _drawerBackdrop?.classList.remove('open');
}

async function openInvoiceDrawer(invoiceId) {
  _ensureDrawer();

  // Reset UI
  document.getElementById('drawer-title').textContent = 'Carregando...';
  document.getElementById('drawer-subtitle').textContent = '';
  document.getElementById('drawer-status').innerHTML = '';
  document.getElementById('drawer-grid').innerHTML = '';
  document.getElementById('drawer-timeline').innerHTML = '';
  document.getElementById('drawer-actions').innerHTML = '';
  document.getElementById('drawer-rejection-box').classList.add('hidden');
  document.getElementById('drawer-review-panel').classList.add('hidden');
  document.getElementById('drawer-pdf-panel').style.display = 'none';
  document.getElementById('drawer-pdf-iframe').src = '';

  const pageLink = document.getElementById('drawer-open-page');
  pageLink.style.display = 'none';

  _drawerBackdrop.classList.add('open');
  _drawerEl.classList.add('open');

  try {
    const invoice = await apiFetch(`/api/invoices/${invoiceId}`);
    _renderDrawerContent(invoice);
    if (invoice.has_attachment) _loadDrawerPdf(invoiceId);
  } catch (e) {
    document.getElementById('drawer-title').textContent = 'Erro ao carregar';
    document.getElementById('drawer-grid').innerHTML = `<p class="text-muted">${escapeHtml(e.message)}</p>`;
  }
}

function _renderDrawerContent(invoice) {
  const user = Auth.getUser();

  document.getElementById('drawer-title').textContent = `Nota ${invoice.invoice_number}`;
  document.getElementById('drawer-subtitle').textContent =
    `${escapeHtml(invoice.created_by.name)} · ${formatDateTime(invoice.created_at)}`;
  renderInvoiceAlerts(invoice, 'drawer-grid');
  document.getElementById('drawer-status').innerHTML = statusBadge(invoice.status);

  // Link para página completa (edição, etc.)
  const pageLink = document.getElementById('drawer-open-page');
  pageLink.href = `/invoices/${invoice.id}`;
  pageLink.style.display = '';

  document.getElementById('drawer-grid').innerHTML = [
    ['Valor',          formatCurrency(invoice.amount)],
    ['Emissao',        formatDate(invoice.issue_date)],
    ['Vencimento',     formatDate(invoice.due_date)],
    ['Setor',          invoice.department_name || '-'],
    ['Descricao',      invoice.description],
    ['Dados bancarios', invoice.bank_details || '-'],
  ].map(([l, v]) => `<div class="detail-item"><span>${l}</span><strong>${escapeHtml(String(v))}</strong></div>`).join('');

  const rejection = [...invoice.history].reverse().find((h) => h.action.startsWith('REJECTED'));
  const rejBox = document.getElementById('drawer-rejection-box');
  if (rejection) {
    rejBox.innerHTML = `<strong>Motivo da reprovacao:</strong> ${escapeHtml(rejection.comment || '-')}`;
    rejBox.classList.remove('hidden');
  }

  const icons  = { CREATED: '+', SUBMITTED: '>', APPROVED_MANAGER: '✓', REJECTED_MANAGER: '✗', APPROVED_DIRECTOR: '✓', REJECTED_DIRECTOR: '✗', MARKED_PAID: '$', PRINTED: '🖨' };
  const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Cancelada', APPROVED_MANAGER: 'Aprovada gestor', REJECTED_MANAGER: 'Reprovada gestor', APPROVED_DIRECTOR: 'Aprovada diretor', REJECTED_DIRECTOR: 'Reprovada diretor', MARKED_PAID: 'Lancada', PRINTED: 'Comprovante impresso' };
  document.getElementById('drawer-timeline').innerHTML = invoice.history.map((h) => `
    <div class="timeline-item">
      <div class="timeline-icon">${icons[h.action] || '·'}</div>
      <div><strong>${labels[h.action] || h.action}</strong>
        <div class="timeline-meta">${escapeHtml(h.user.name)} · ${formatDateTime(h.timestamp)}</div>
        ${h.comment ? `<p>${escapeHtml(h.comment)}</p>` : ''}
      </div>
    </div>`).join('');

  _renderDrawerActions(invoice, user);
}

async function _renderDrawerActions(invoice, user) {
  const role = user?.role;

  // Gestor revisando
  if (role === 'MANAGER' && invoice.status === 'AGUARDANDO_GESTOR') {
    return _renderDrawerManagerReview(invoice);
  }
  // Diretor revisando
  if (role === 'DIRECTOR' && invoice.status === 'AGUARDANDO_DIRETOR') {
    return _renderDrawerDirectorReview(invoice);
  }
  // Financeiro — imprimir comprovante (APROVADO = 1a impressao | PAGO = reimpressao)
  if (role === 'FINANCE' && (invoice.status === 'APROVADO' || invoice.status === 'PAGO')) {
    return _renderDrawerFinance(invoice);
  }

  // Funcionário / criador da nota
  const actionsEl = document.getElementById('drawer-actions');
  const isDirect = Boolean(user?.submit_directly_to_director);
  const buttons = [];

  if (invoice.can_cancel) {
    buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
  }
  if (invoice.status === 'RASCUNHO') {
    buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
    buttons.push(isDirect
      ? '<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>'
      : '<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
    buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
  }
  if (invoice.status.startsWith('REPROVADO')) {
    buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
  }

  let dirHtml = '';
  if (invoice.status === 'RASCUNHO' && isDirect) {
    dirHtml = `<div class="form-group" style="margin-bottom:1rem">
      <label class="form-label">Enviar para o diretor:</label>
      <div id="drawer-dir-list" class="director-list"><p class="text-muted">Carregando...</p></div>
      <input type="hidden" id="drawer-dir-chosen">
    </div>`;
  }
  actionsEl.innerHTML = dirHtml + buttons.join('');

  if (invoice.status === 'RASCUNHO' && isDirect) {
    try {
      const dirs = await apiFetch('/api/invoices/directors');
      renderDirectorList(dirs, 'drawer-dir-list', 'drawer-dir-chosen');
    } catch {
      const el = document.getElementById('drawer-dir-list');
      if (el) el.innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
    }
  }

  actionsEl.querySelectorAll('button[data-action]').forEach((btn) => {
    btn.addEventListener('click', async () => {
      try {
        if (btn.dataset.action === 'submit') {
          await apiFetch(`/api/invoices/${invoice.id}/submit`, { method: 'POST' });
          showToast('Nota enviada para o gestor.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'submit-direct') {
          const dirId = document.getElementById('drawer-dir-chosen')?.value;
          if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
          await apiFetch(`/api/invoices/${invoice.id}/submit?director_id=${encodeURIComponent(dirId)}`, { method: 'POST' });
          showToast('Nota enviada para o diretor.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'cancel') {
          if (!(await confirmAction('Cancelar esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}/cancel`, { method: 'POST' });
          showToast('Nota cancelada.', 'success');
          _refreshAfterAction();
        } else if (btn.dataset.action === 'delete') {
          if (!(await confirmAction('Excluir esta nota?'))) return;
          await apiFetch(`/api/invoices/${invoice.id}`, { method: 'DELETE' });
          showToast('Nota excluida.', 'success');
          _refreshAfterAction();
        }
      } catch (e) { showToast(e.message, 'error'); }
    });
  });
}

async function _renderDrawerManagerReview(invoice) {
  const panel = document.getElementById('drawer-review-panel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <h3>Revisar nota</h3>
    <div style="margin-bottom:1rem">
      <label class="form-label">Encaminhar para o diretor:</label>
      <div id="drawer-mgr-dir-list" class="director-list"><p class="text-muted">Carregando...</p></div>
      <input type="hidden" id="drawer-mgr-dir-chosen">
    </div>
    <div class="review-actions">
      <button class="btn btn-primary" id="drawer-mgr-approve">Aprovar e encaminhar</button>
      <button class="btn btn-ghost" id="drawer-mgr-show-reject">Reprovar</button>
    </div>
    <div id="drawer-mgr-reject-sec" class="hidden" style="margin-top:1rem">
      <label class="form-label">Motivo da reprovacao (obrigatorio)</label>
      <textarea id="drawer-mgr-reject-txt" class="form-input" rows="3" maxlength="500" placeholder="Minimo 10 caracteres..."></textarea>
      <div class="review-actions" style="margin-top:.5rem">
        <button class="btn btn-danger" id="drawer-mgr-confirm-reject" disabled>Confirmar reprovacao</button>
        <button class="btn btn-ghost" id="drawer-mgr-cancel-reject">Cancelar</button>
      </div>
    </div>`;

  try {
    const dirs = await apiFetch('/api/invoices/directors');
    renderDirectorList(dirs, 'drawer-mgr-dir-list', 'drawer-mgr-dir-chosen');
  } catch {
    document.getElementById('drawer-mgr-dir-list').innerHTML = '<p class="text-muted">Erro ao carregar diretores.</p>';
  }

  document.getElementById('drawer-mgr-approve').addEventListener('click', async () => {
    const dirId = document.getElementById('drawer-mgr-dir-chosen')?.value;
    if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
    try {
      await apiFetch(`/api/invoices/${invoice.id}/review`, {
        method: 'POST',
        body: JSON.stringify({ action: 'APPROVE', director_id: dirId })
      });
      showToast('Nota aprovada e encaminhada ao diretor.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });

  _wireDrawerReject('drawer-mgr-show-reject', 'drawer-mgr-reject-sec', 'drawer-mgr-cancel-reject',
    'drawer-mgr-reject-txt', 'drawer-mgr-confirm-reject', async (comment) => {
      await apiFetch(`/api/invoices/${invoice.id}/review`, {
        method: 'POST', body: JSON.stringify({ action: 'REJECT', comment })
      });
    });
}

function _renderDrawerDirectorReview(invoice) {
  const panel = document.getElementById('drawer-review-panel');
  panel.classList.remove('hidden');
  panel.innerHTML = `
    <h3>Decisao do Diretor</h3>
    <div class="review-actions">
      <button class="btn btn-primary" id="drawer-dir-approve">Aprovar nota</button>
      <button class="btn btn-ghost" id="drawer-dir-show-reject">Reprovar</button>
    </div>
    <div id="drawer-dir-reject-sec" class="hidden" style="margin-top:1rem">
      <label class="form-label">Motivo da reprovacao (obrigatorio)</label>
      <textarea id="drawer-dir-reject-txt" class="form-input" rows="3" maxlength="500" placeholder="Minimo 10 caracteres..."></textarea>
      <div class="review-actions" style="margin-top:.5rem">
        <button class="btn btn-danger" id="drawer-dir-confirm-reject" disabled>Confirmar reprovacao</button>
        <button class="btn btn-ghost" id="drawer-dir-cancel-reject">Cancelar</button>
      </div>
    </div>`;

  document.getElementById('drawer-dir-approve').addEventListener('click', async () => {
    try {
      await apiFetch(`/api/invoices/${invoice.id}/director-review`, {
        method: 'POST', body: JSON.stringify({ action: 'APPROVE' })
      });
      showToast('Nota aprovada.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });

  _wireDrawerReject('drawer-dir-show-reject', 'drawer-dir-reject-sec', 'drawer-dir-cancel-reject',
    'drawer-dir-reject-txt', 'drawer-dir-confirm-reject', async (comment) => {
      await apiFetch(`/api/invoices/${invoice.id}/director-review`, {
        method: 'POST', body: JSON.stringify({ action: 'REJECT', comment })
      });
    });
}

function _renderDrawerFinance(invoice) {
  const actionsEl = document.getElementById('drawer-actions');
  const printedEntry = invoice.history.slice().reverse().find((h) => h.action === 'PRINTED');
  const lastPrint = printedEntry
    ? `<p class="receipt-last-print">Ultima impressao: ${formatDateTime(printedEntry.timestamp)} por ${escapeHtml(printedEntry.user.name)}</p>`
    : '';
  const isReprint = invoice.status === 'PAGO';
  const titleTxt = isReprint ? 'Re-imprimir Comprovante' : 'Comprovante de Recebimento';
  const descTxt = isReprint
    ? 'Nota ja foi lancada. Reimpressao gera novo comprovante sem alterar o status.'
    : 'Trilha completa + QR code + PDF original. Ao imprimir, registra o lancamento automaticamente.';
  const btnTxt = isReprint ? 'Re-imprimir Comprovante' : 'Imprimir e Lancar Nota';
  const btnClass = isReprint ? 'btn-ghost' : 'btn-primary';

  actionsEl.innerHTML = `
    <div class="receipt-card">
      <div class="receipt-card-icon">🖨</div>
      <div class="receipt-card-body">
        <strong>${titleTxt}</strong>
        <p>${descTxt}</p>
        ${lastPrint}
      </div>
      <div class="receipt-card-actions">
        <button class="btn ${btnClass}" id="drawer-finance-print">${btnTxt}</button>
      </div>
    </div>`;

  document.getElementById('drawer-finance-print').addEventListener('click', async () => {
    const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/print`);
    if (ok) {
      showToast(isReprint ? 'Comprovante reimpresso.' : 'Comprovante gerado. Nota lancada.', 'success');
      setTimeout(async () => {
        const updated = await apiFetch(`/api/invoices/${invoice.id}`);
        _renderDrawerContent(updated);
        if (updated.has_attachment) _loadDrawerPdf(invoice.id);
      }, 1200);
    }
  });
}

function _wireDrawerReject(showId, sectionId, cancelId, txtId, confirmId, onConfirm) {
  document.getElementById(showId)?.addEventListener('click', () => {
    document.getElementById(sectionId)?.classList.remove('hidden');
    document.getElementById(showId)?.setAttribute('disabled', '');
  });
  document.getElementById(cancelId)?.addEventListener('click', () => {
    document.getElementById(sectionId)?.classList.add('hidden');
    document.getElementById(showId)?.removeAttribute('disabled');
  });
  const txt = document.getElementById(txtId);
  const confirmBtn = document.getElementById(confirmId);
  txt?.addEventListener('input', () => { if (confirmBtn) confirmBtn.disabled = txt.value.trim().length < 10; });
  confirmBtn?.addEventListener('click', async () => {
    const comment = txt.value.trim();
    if (comment.length < 10) return;
    try {
      await onConfirm(comment);
      showToast('Nota reprovada.', 'success');
      _refreshAfterAction();
    } catch (e) { showToast(e.message, 'error'); }
  });
}

function _refreshAfterAction() {
  closeDrawer();
  setTimeout(() => window.location.reload(), 400);
}

async function _loadDrawerPdf(invoiceId) {
  const panel = document.getElementById('drawer-pdf-panel');
  if (!panel) return;
  try {
    const token = Auth.getToken();
    const resp = await fetch(`/api/invoices/${invoiceId}/attachment`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {}
    });
    if (!resp.ok) return;
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const iframe = document.getElementById('drawer-pdf-iframe');
    const link = document.getElementById('drawer-pdf-link');
    if (iframe) iframe.src = url;
    if (link) link.href = url;
    panel.style.display = 'block';
  } catch {}
}

// ── Admin Departments ────────────────────────────────────────────────────────

async function initAdminDepartments() {
  let editingDeptId = null;
  let allDirectors = [];

  async function loadDirectors() {
    try { allDirectors = await apiFetch('/api/admin/directors'); } catch { allDirectors = []; }
  }

  async function loadDepartments() {
    const list = document.getElementById('departments-list');
    try {
      const depts = await apiFetch('/api/admin/departments');
      if (!depts.length) {
        list.innerHTML = '<p class="text-muted" style="padding:1.5rem">Nenhum setor cadastrado ainda.</p>';
        return;
      }
      list.innerHTML = depts.map((d) => `
        <div class="card dept-card">
          <div class="dept-info">
            <strong>${escapeHtml(d.name)}</strong>
            ${d.description ? `<p class="text-muted">${escapeHtml(d.description)}</p>` : ''}
            <div class="dept-meta">
              <span>${d.members_count} membro${d.members_count !== 1 ? 's' : ''}</span>
              ${d.directors.length
                ? `<span>Diretores: ${d.directors.map((dr) => escapeHtml(dr.name)).join(', ')}</span>`
                : '<span class="text-muted">Sem diretor vinculado</span>'}
            </div>
          </div>
          <div class="dept-actions">
            <button class="btn btn-ghost btn-sm" data-edit="${d.id}">Editar</button>
            ${d.members_count === 0 ? `<button class="btn btn-ghost btn-sm text-danger" data-delete="${d.id}">Excluir</button>` : ''}
          </div>
        </div>`).join('');
      list.querySelectorAll('[data-edit]').forEach((btn) => {
        const dept = depts.find((d) => d.id === btn.dataset.edit);
        btn.addEventListener('click', () => openDeptModal(dept));
      });
      list.querySelectorAll('[data-delete]').forEach((btn) => {
        btn.addEventListener('click', () => deleteDept(btn.dataset.delete));
      });
    } catch (e) {
      list.innerHTML = `<p class="text-muted">Erro ao carregar setores: ${escapeHtml(e.message)}</p>`;
    }
  }

  function openDeptModal(dept) {
    editingDeptId = dept ? dept.id : null;
    document.getElementById('dept-modal-title').textContent = dept ? 'Editar Setor' : 'Novo Setor';
    document.getElementById('dept-name').value = dept ? dept.name : '';
    document.getElementById('dept-desc').value = dept ? (dept.description || '') : '';
    const container = document.getElementById('directors-checkboxes');
    const selectedIds = dept ? dept.directors.map((d) => d.id) : [];
    container.innerHTML = allDirectors.length
      ? allDirectors.map((d) => `<label class="checkbox-label">
          <input type="checkbox" value="${d.id}"${selectedIds.includes(d.id) ? ' checked' : ''}>
          ${escapeHtml(d.name)}</label>`).join('')
      : '<p class="text-muted">Nenhum diretor ativo cadastrado</p>';
    document.getElementById('dept-modal').classList.remove('hidden');
    document.getElementById('dept-name').focus();
  }

  function closeDeptModal() {
    document.getElementById('dept-modal').classList.add('hidden');
    editingDeptId = null;
  }

  async function saveDept() {
    const name = document.getElementById('dept-name').value.trim();
    if (!name) { showToast('Informe o nome do setor', 'error'); return; }
    const directorIds = [...document.querySelectorAll('#directors-checkboxes input:checked')].map((c) => c.value);
    const body = { name, description: document.getElementById('dept-desc').value.trim() || null, director_ids: directorIds };
    try {
      if (editingDeptId) {
        await apiFetch(`/api/admin/departments/${editingDeptId}`, { method: 'PUT', body: JSON.stringify(body) });
        showToast('Setor atualizado', 'success');
      } else {
        await apiFetch('/api/admin/departments', { method: 'POST', body: JSON.stringify(body) });
        showToast('Setor criado', 'success');
      }
      closeDeptModal();
      await loadDepartments();
    } catch (e) { showToast(e.message, 'error'); }
  }

  async function deleteDept(id) {
    if (!(await confirmAction('Excluir este setor?'))) return;
    try {
      await apiFetch(`/api/admin/departments/${id}`, { method: 'DELETE' });
      showToast('Setor excluido', 'success');
      await loadDepartments();
    } catch (e) { showToast(e.message, 'error'); }
  }

  await Promise.all([loadDirectors(), loadDepartments()]);

  document.getElementById('btn-new-dept').addEventListener('click', () => openDeptModal(null));
  document.getElementById('dept-modal-cancel').addEventListener('click', closeDeptModal);
  document.getElementById('dept-modal-save').addEventListener('click', saveDept);
  document.getElementById('dept-modal').addEventListener('click', (e) => {
    if (e.target === document.getElementById('dept-modal')) closeDeptModal();
  });
}

// ── Listeners globais (ESC fecha modal, click no backdrop fecha) ────────────

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') {
    // Fecha o ultimo modal visivel (z-index mais alto)
    const open = document.querySelectorAll('.modal-backdrop:not(.hidden)');
    if (open.length) {
      open[open.length - 1].classList.add('hidden');
      event.stopPropagation();
    }
    // Fecha drawer aberto
    const drawer = document.querySelector('.drawer-backdrop:not(.hidden)');
    if (drawer) drawer.classList.add('hidden');
  }
});
document.addEventListener('click', (event) => {
  // Click no backdrop (nao no conteudo interno) fecha o modal
  if (event.target.classList?.contains('modal-backdrop')) {
    event.target.classList.add('hidden');
  }
  if (event.target.classList?.contains('drawer-backdrop')) {
    event.target.classList.add('hidden');
  }
});


// ── DOMContentLoaded dispatch ────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  const page = document.body.dataset.page;
  if (page === 'login') {
    if (Auth.getToken()) window.location.href = '/dashboard';
    document.getElementById('login-form')?.addEventListener('submit', handleLogin);
    document.getElementById('toggle-password')?.addEventListener('click', togglePasswordVisibility);
    return;
  }
  if (page === 'change-password') {
    initChangePasswordPage();
    return;
  }
  document.getElementById('sidebar-toggle')?.addEventListener('click', toggleSidebar);
  document.getElementById('logout-btn')?.addEventListener('click', logout);

  // Global drawer delegation — any [data-drawer] button opens the slide-in drawer
  document.addEventListener('click', (event) => {
    const btn = event.target.closest('[data-drawer]');
    if (btn) {
      event.preventDefault();
      openInvoiceDrawer(btn.dataset.drawer);
    }
  });

  if (page === 'dashboard') {
    initShell().then(() => initDashboard());
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
  } else if (page === 'admin-smtp') {
    initShell().then(() => initAdminSmtp());
  } else if (page === 'configuracoes') {
    initShell().then(() => initConfiguracoes());
  } else if (page === 'forgot-password') {
    initForgotPasswordPage();
  } else if (page === 'reset-password') {
    initResetPasswordPage();
  } else if (document.querySelector('.layout')) {
    initShell();
  }
});


// ─── Esqueci minha senha ──────────────────────────────────────────────────

function initForgotPasswordPage() {
  document.getElementById('forgot-password-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = document.getElementById('forgot-email').value.trim();
    if (!email) return;
    const msgEl = document.getElementById('forgot-message');
    try {
      await fetch('/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      msgEl.textContent = 'Se este email estiver cadastrado, voce recebera um codigo em alguns segundos. Verifique sua caixa de entrada e spam.';
      msgEl.classList.remove('hidden');
      setTimeout(() => { window.location.href = `/reset-password?email=${encodeURIComponent(email)}`; }, 2500);
    } catch (e) {
      showToast('Erro ao processar pedido. Tente novamente.', 'error');
    }
  });
}

function initResetPasswordPage() {
  // Pre-preenche email se veio via querystring
  const params = new URLSearchParams(window.location.search);
  const emailParam = params.get('email');
  if (emailParam) document.getElementById('reset-email').value = emailParam;

  document.getElementById('reset-password-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const errorEl = document.getElementById('reset-error');
    errorEl.classList.add('hidden');
    const payload = {
      email: document.getElementById('reset-email').value.trim(),
      code: document.getElementById('reset-code').value.trim(),
      new_password: document.getElementById('reset-new-password').value
    };
    try {
      const resp = await fetch('/auth/reset-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || 'Erro');
      showToast('Senha redefinida! Faca login com a nova senha.', 'success');
      setTimeout(() => { window.location.href = '/login'; }, 1500);
    } catch (e) {
      errorEl.textContent = e.message;
      errorEl.classList.remove('hidden');
    }
  });
}


// ─── Admin SMTP ───────────────────────────────────────────────────────────

const SMTP_PRESETS = {
  gmail:    { host: 'smtp.gmail.com',         port: 587, tls: true },
  outlook:  { host: 'smtp.office365.com',     port: 587, tls: true },
  sendgrid: { host: 'smtp.sendgrid.net',      port: 2525, tls: true },
};

async function initAdminSmtp() {
  document.getElementById('smtp-form')?.addEventListener('submit', saveAdminSmtp);
  document.getElementById('smtp-edit-btn')?.addEventListener('click', showSmtpForm);
  document.getElementById('smtp-cancel-btn')?.addEventListener('click', loadAdminSmtp);
  document.getElementById('smtp-test-btn')?.addEventListener('click', testSmtp);
  document.getElementById('smtp-provider')?.addEventListener('change', toggleSmtpProviderFields);
  // Botoes de preset SMTP
  document.querySelectorAll('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const p = SMTP_PRESETS[btn.dataset.preset];
      if (!p) return;
      document.getElementById('smtp-host').value = p.host;
      document.getElementById('smtp-port').value = p.port;
      document.getElementById('smtp-use-tls').checked = p.tls;
    });
  });
  await loadAdminSmtp();
}

function toggleSmtpProviderFields() {
  const provider = document.getElementById('smtp-provider').value;
  const isResend = provider === 'RESEND';
  document.getElementById('smtp-resend-fields').classList.toggle('hidden', !isResend);
  document.getElementById('smtp-smtp-fields').classList.toggle('hidden', isResend);
}

async function loadAdminSmtp() {
  try {
    const cfg = await apiFetch('/api/admin/smtp');
    const summary = document.getElementById('smtp-summary');
    const form = document.getElementById('smtp-form');
    if (cfg.configured && cfg.has_password) {
      const providerLabel = cfg.provider === 'RESEND' ? 'Resend (HTTP API)' : 'SMTP';
      document.getElementById('smtp-status-badge').innerHTML = cfg.enabled
        ? '<span class="status-badge status-aprovado">Ativo</span>'
        : '<span class="status-badge status-rascunho">Desabilitado</span>';
      document.getElementById('smtp-summary-provider').textContent = providerLabel;
      document.getElementById('smtp-summary-host').textContent =
        cfg.provider === 'RESEND' ? 'api.resend.com (HTTP)' : `${cfg.smtp_host}:${cfg.smtp_port}`;
      document.getElementById('smtp-summary-from').textContent = cfg.smtp_from_email;
      document.getElementById('smtp-summary-updated').textContent =
        cfg.updated_at ? `Atualizado em ${formatDateTime(cfg.updated_at)}` : '';
      summary.classList.remove('hidden');
      form.classList.add('hidden');
    } else {
      summary.classList.add('hidden');
      showSmtpForm(null, cfg);
    }
  } catch (e) {
    showToast(e.message, 'error');
  }
}

function showSmtpForm(_evt, cfg) {
  const form = document.getElementById('smtp-form');
  const summary = document.getElementById('smtp-summary');
  if (!cfg) {
    apiFetch('/api/admin/smtp').then((data) => populateSmtpForm(data));
  } else {
    populateSmtpForm(cfg);
  }
  form.classList.remove('hidden');
  summary.classList.add('hidden');
}

function populateSmtpForm(cfg) {
  document.getElementById('smtp-provider').value = cfg.provider || 'RESEND';
  toggleSmtpProviderFields();
  // SMTP fields
  document.getElementById('smtp-host').value = cfg.smtp_host || '';
  document.getElementById('smtp-port').value = cfg.smtp_port || 587;
  document.getElementById('smtp-user').value = cfg.smtp_user || '';
  document.getElementById('smtp-from-email').value = cfg.smtp_from_email || '';
  document.getElementById('smtp-from-name').value = cfg.smtp_from_name || 'Economart Notas';
  document.getElementById('smtp-use-tls').checked = cfg.use_tls !== false;
  document.getElementById('smtp-password').value = '';
  // Resend fields
  document.getElementById('smtp-resend-from').value = cfg.smtp_from_email || '';
  document.getElementById('smtp-resend-from-name').value = cfg.smtp_from_name || 'Economart Notas';
  document.getElementById('smtp-resend-key').value = '';
  // Comum
  document.getElementById('smtp-enabled').checked = cfg.enabled !== false;
  // Help text de senha
  const smtpHelp = document.getElementById('smtp-password-required');
  const resendHelp = document.getElementById('smtp-resend-key-required');
  if (cfg.has_password) {
    [smtpHelp, resendHelp].forEach((el) => { if (el) el.textContent = '(em branco = manter atual)'; });
    document.getElementById('smtp-password').placeholder = '••••••••••••••••';
    document.getElementById('smtp-resend-key').placeholder = 're_••••••••••••••••';
  } else {
    [smtpHelp, resendHelp].forEach((el) => { if (el) el.textContent = '*'; });
  }
}

async function saveAdminSmtp(event) {
  event.preventDefault();
  const provider = document.getElementById('smtp-provider').value;
  let payload;
  if (provider === 'RESEND') {
    payload = {
      provider: 'RESEND',
      smtp_from_email: document.getElementById('smtp-resend-from').value.trim(),
      smtp_from_name: document.getElementById('smtp-resend-from-name').value.trim(),
      smtp_host: 'api.resend.com',
      smtp_port: 443,
      smtp_user: 'resend',
      use_tls: true,
      enabled: document.getElementById('smtp-enabled').checked,
    };
    const key = document.getElementById('smtp-resend-key').value.trim();
    if (key) payload.smtp_password = key;
  } else {
    payload = {
      provider: 'SMTP',
      smtp_host: document.getElementById('smtp-host').value.trim(),
      smtp_port: parseInt(document.getElementById('smtp-port').value, 10) || 587,
      smtp_user: document.getElementById('smtp-user').value.trim(),
      smtp_from_email: document.getElementById('smtp-from-email').value.trim(),
      smtp_from_name: document.getElementById('smtp-from-name').value.trim(),
      use_tls: document.getElementById('smtp-use-tls').checked,
      enabled: document.getElementById('smtp-enabled').checked,
    };
    const password = document.getElementById('smtp-password').value;
    if (password) payload.smtp_password = password;
  }
  try {
    await apiFetch('/api/admin/smtp', { method: 'PUT', body: JSON.stringify(payload) });
    showToast('Configuracao salva com sucesso.', 'success');
    await loadAdminSmtp();
  } catch (e) {
    showToast(e.message, 'error');
  }
}

async function testSmtp() {
  const btn = document.getElementById('smtp-test-btn');
  btn.disabled = true;
  btn.textContent = 'Enviando...';
  try {
    const resp = await apiFetch('/api/admin/smtp/test', { method: 'POST' });
    showToast(resp.message || 'Email de teste enviado!', 'success');
  } catch (e) {
    showToast(e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Enviar email de teste';
  }
}
