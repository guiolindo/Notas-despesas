/* shell.js — login + initShell (header/menu) + configuracoes.
 * Depende de window.Auth, window.apiFetch, window.showToast, window._wireSidebarMobile,
 * window._wireGlobalShortcuts, window.ROLE_LABELS.
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  function getSafeNextParam() {
    try {
      const raw = new URLSearchParams(window.location.search).get('next');
      if (!raw) return null;
      if (!raw.startsWith('/') || raw.startsWith('//')) return null;
      if (raw.startsWith('/login') || raw.startsWith('/change-password')) return null;
      return raw;
    } catch {
      return null;
    }
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
      if (data.user.must_change_password) {
        window.location.href = '/change-password';
      } else {
        const next = getSafeNextParam();
        window.location.href = next || '/dashboard';
      }
    } catch {
      errorEl.textContent = 'Erro de conexao. Tente novamente.';
      errorEl.classList.remove('hidden');
    } finally {
      button.disabled = false;
      button.textContent = 'Entrar';
    }
  }

  async function initShell() {
    let user = Auth.getUser();
    if (!user) { window.location.href = '/login'; return; }
    try {
      const fresh = await apiFetch('/auth/me');
      user = { ...user, ...fresh };
      Auth.setUser(user);
    } catch {}
    if (user.must_change_password && window.location.pathname !== '/change-password') {
      window.location.href = '/change-password';
      return;
    }
    document.getElementById('header-user-name').textContent = user.name;
    _wireSidebarMobile();
    _wireGlobalShortcuts();
    document.getElementById('header-user-role').textContent = ROLE_LABELS[user.role] || user.role;
    addApprovalQueueLink(user.role);
    renderGlobalAvailabilityBanner();
    // Alerts em fire-and-forget pra nao bloquear init da pagina.
    apiFetch('/alerts/').then((data) => {
      const count = (data && data.summary && data.summary.total_alerts) || 0;
      if (count > 0) {
        const el = document.getElementById('alert-count');
        if (el) {
          el.textContent = count;
          el.classList.remove('hidden');
        }
      }
    }).catch(() => {});
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
      nav.insertBefore(users, document.getElementById('nav-alerts'));
      nav.insertBefore(depts, document.getElementById('nav-alerts'));
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
    }
    if (role === 'CONTAS_A_PAGAR' && !document.getElementById('nav-scanner')) {
      const scan = document.createElement('a');
      scan.href = '/contas-a-pagar/scanner';
      scan.id = 'nav-scanner';
      scan.className = 'nav-item';
      scan.innerHTML = '<span class="nav-icon">&#9783;</span> Scanner QR';
      nav.insertBefore(scan, document.getElementById('nav-alerts'));
      document.getElementById('nav-new-invoice')?.remove();
    }
  }

  async function initConfiguracoes() {
    const user = Auth.getUser();
    if (!user) return;
    const card = document.getElementById('config-availability-card');
    if (!['MANAGER', 'DIRECTOR'].includes(user.role)) return;
    card.classList.remove('hidden');
    const me = await apiFetch('/auth/me');
    const toggle = document.getElementById('config-unavailable-toggle');
    toggle.checked = Boolean(me.unavailable_for_notes);
    document.getElementById('config-availability-status')
      .classList.toggle('hidden', !me.unavailable_for_notes);
    const subSection = document.getElementById('config-substitute-section');
    const subSel = document.getElementById('config-substitute-select');
    if (user.role === 'DIRECTOR' && subSection && subSel) {
      subSection.classList.remove('hidden');
      try {
        const allDirectors = await apiFetch('/api/invoices/directors');
        allDirectors
          .filter((d) => d.id !== user.id && d.is_active && !d.unavailable_for_notes)
          .forEach((d) => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = d.name + (d.department_name ? ` · ${d.department_name}` : '');
            if (d.id === me.substitute_director_id) opt.selected = true;
            subSel.appendChild(opt);
          });
      } catch {
        subSection.classList.add('hidden');
      }
    }
    async function applyChange() {
      const payload = {
        unavailable: toggle.checked,
        substitute_director_id: subSel ? (subSel.value || null) : null,
      };
      try {
        const resp = await apiFetch('/auth/me/availability', {
          method: 'PUT',
          body: JSON.stringify(payload),
        });
        showToast(resp.message, 'success');
        document.getElementById('config-availability-status')
          .classList.toggle('hidden', !toggle.checked);
        Auth.setUser({
          ...user,
          unavailable_for_notes: toggle.checked,
          substitute_director_id: payload.substitute_director_id,
        });
        renderGlobalAvailabilityBanner();
      } catch (e) {
        toggle.checked = !toggle.checked;
        showToast(e.message, 'error');
      }
    }
    toggle.addEventListener('change', applyChange);
    if (subSel) subSel.addEventListener('change', applyChange);
  }

  function renderGlobalAvailabilityBanner() {
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

  window.Economart.shell = {
    logout, togglePasswordVisibility, getSafeNextParam, handleLogin,
    initShell, addApprovalQueueLink, renderGlobalAvailabilityBanner,
    initConfiguracoes,
  };
  window.logout = logout;
  window.togglePasswordVisibility = togglePasswordVisibility;
  window.getSafeNextParam = getSafeNextParam;
  window.handleLogin = handleLogin;
  window.initShell = initShell;
  window.addApprovalQueueLink = addApprovalQueueLink;
  window.renderGlobalAvailabilityBanner = renderGlobalAvailabilityBanner;
  window.initConfiguracoes = initConfiguracoes;
})();
