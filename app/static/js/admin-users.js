/* admin-users.js — CRUD de usuarios (admin). */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  const adminRoleLabels = { ...(window.ROLE_LABELS || {}), ADMIN: 'Admin', FINANCE: 'Financeiro' };
  let adminUsersCache = [];

  function adminRoleBadge(role) {
    const cls = String(role).toLowerCase().replace(/_/g, '-');
    const code = {
      ADMIN: 'ADM', FINANCE: 'FIN', CONTAS_A_PAGAR: 'CAP',
      DIRECTOR: 'DIR', MANAGER: 'GES', EMPLOYEE: 'FUN',
    }[role] || String(role).slice(0, 3).toUpperCase();
    return `<span class="role-chip role-${cls}"><span class="role-chip-code" aria-hidden="true">${escapeHtml(code)}</span><span>${escapeHtml(adminRoleLabels[role] || role)}</span></span>`;
  }

  function adminAvatar(name) {
    if (!name) return '<span class="avatar">?</span>';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    const first = parts[0]?.[0] || '';
    const last = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return `<span class="avatar">${escapeHtml((first + last).toUpperCase())}</span>`;
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
    } catch (error) { showToast(error.message, 'error'); }
  }

  function applyAdminUsersFilter() {
    const term = (document.getElementById('admin-users-search')?.value || '').trim().toLowerCase();
    const roleFilter = document.getElementById('admin-users-role-filter')?.value || '';
    const statusFilter = document.getElementById('admin-users-status-filter')?.value || '';
    const filtered = (adminUsersCache || []).filter((user) => {
      if (term) {
        const haystack = [user.name, user.email, user.role, user.department_name, user.id].filter(Boolean).join(' ').toLowerCase();
        if (!haystack.includes(term)) return false;
      }
      if (roleFilter && user.role !== roleFilter) return false;
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
      const msg = total === 0 ? 'Nenhum usuario cadastrado.' : 'Nenhum usuario corresponde aos filtros aplicados.';
      tbody.innerHTML = `<tr><td colspan="7" class="text-muted">${msg}</td></tr>`;
      return;
    }
    const me = Auth.getUser();
    tbody.innerHTML = users.map((user) => {
      const blocked = user.blocked_until && new Date(user.blocked_until) > new Date();
      const isAdmin = user.role === 'ADMIN';
      const isSelf = user.id === me?.id;
      const isAnon = Boolean(user.is_anonymized);
      const toggleBtn = (!isAdmin && !isSelf && !isAnon)
        ? `<button class="btn ${user.is_active ? 'btn-ghost' : 'btn-secondary'} btn-sm" data-action="toggle" data-id="${user.id}" data-active="${user.is_active}" title="${user.is_active ? 'Desativar' : 'Ativar'}" aria-label="${user.is_active ? 'Desativar' : 'Ativar'}"><span class="icon icon-${user.is_active ? 'eye-off' : 'eye'} ic-16"></span></button>`
        : '';
      const unlockBtn = (blocked && !isAdmin && !isAnon)
        ? `<button class="btn btn-ghost btn-sm" data-action="unlock" data-id="${user.id}" title="Desbloquear" aria-label="Desbloquear"><span class="icon icon-circle-check ic-16"></span></button>`
        : '';
      const anonymizeBtn = (!isAdmin && !isSelf && !user.is_active && !isAnon)
        ? `<button class="btn btn-ghost btn-sm btn-danger-text" data-action="anonymize" data-id="${user.id}" data-name="${escapeHtml(user.name)}" title="Encerrar conta" aria-label="Encerrar conta"><span class="icon icon-archive ic-16"></span></button>`
        : '';
      const editBtns = isAnon
        ? '<span class="text-muted text-xs" title="Conta encerrada — registro preservado para auditoria fiscal">Conta encerrada</span>'
        : `
          <a class="btn btn-ghost btn-sm" href="/admin/users/${user.id}/edit" title="Editar completo" aria-label="Editar completo"><span class="icon icon-external-link ic-16"></span></a>
          <button class="btn btn-ghost btn-sm" data-action="quick-edit" data-id="${user.id}" title="Editar rapido" aria-label="Editar rapido"><span class="icon icon-pencil ic-16"></span></button>
          <button class="btn btn-ghost btn-sm" data-action="reset" data-id="${user.id}" title="Redefinir senha" aria-label="Redefinir senha"><span class="icon icon-lock ic-16"></span></button>
        `;
      const rowCls = isAdmin ? ' class="row-admin"' : (isAnon ? ' class="row-anonymized"' : '');
      const nameCell = `<div class="user-name-cell">${adminAvatar(user.name)}<div><strong>${escapeHtml(user.name)}</strong>${isSelf ? ' <span class="badge-self">voce</span>' : ''}${isAnon ? ' <span class="badge-anon">encerrada</span>' : ''}</div></div>`;
      return `<tr${rowCls} data-user-id="${user.id}" data-anonymized="${isAnon}">
        <td>${nameCell}</td>
        <td>${escapeHtml(user.email)}</td>
        <td>${adminRoleBadge(user.role)}</td>
        <td>${escapeHtml(user.department_name || '-')}</td>
        <td>${adminUserStatus(user)}</td>
        <td>${formatDateTime(user.last_login)}</td>
        <td class="table-actions">${editBtns}${unlockBtn}${toggleBtn}${anonymizeBtn}</td>
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
    if (action === 'anonymize') await anonymizeAdminUser(id, button.dataset.name);
  }

  async function anonymizeAdminUser(userId, userName) {
    const msg =
      `Encerrar definitivamente a conta de "${userName}"?\n\n` +
      `Nome, email e senha serao substituidos por placeholders. ` +
      `O usuario nao podera mais logar.\n\n` +
      `O historico de aprovacoes e preservado por exigencia fiscal (5 anos).\n\n` +
      `Esta acao nao pode ser desfeita.`;
    if (!(await confirmAction(msg))) return;
    try {
      const resp = await apiFetch(`/api/admin/users/${userId}/anonymize`, { method: 'POST' });
      showToast(resp.message || 'Usuario anonimizado.', 'success');
      await loadAdminUsers();
    } catch (e) { showToast(e.message, 'error'); }
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
    } catch (error) { showToast(error.message, 'error'); }
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
    } catch (error) { showToast(error.message, 'error'); }
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
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function unlockAdminUser(userId) {
    try {
      await apiFetch(`/api/admin/users/${userId}/unlock`, { method: 'POST' });
      showToast('Usuario desbloqueado.', 'success');
      await loadAdminUsers();
    } catch (error) { showToast(error.message, 'error'); }
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
    } catch (error) { showToast(error.message, 'error'); }
  }

  async function initAdminUserForm() {
    const page = document.getElementById('admin-user-form-page');
    const mode = page.dataset.mode;
    const userId = page.dataset.userId;
    if (mode === 'edit') {
      let allowed = false;
      try {
        const expected = sessionStorage.getItem('admin_edit_target_id');
        if (expected === userId) {
          allowed = true;
          sessionStorage.removeItem('admin_edit_target_id');
        }
      } catch (e) {}
      if (!allowed) {
        showToast('Selecione o usuario na lista antes de editar.', 'info');
        setTimeout(() => { window.location.href = '/admin/users'; }, 1500);
        return;
      }
    }
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
      const card = document.getElementById('edit-context-card');
      if (card) {
        card.classList.remove('hidden');
        const setText = (id, val) => {
          const el = document.getElementById(id);
          if (el) el.textContent = val || '—';
        };
        setText('edit-target-name', user.name);
        setText('edit-target-email', user.email);
        setText('edit-target-role', user.role);
        const me = Auth.getUser();
        setText('edit-acting-user', me ? (me.name || me.email || '') : '');
        const isSelf = me && me.id === user.id;
        const selfWarn = document.getElementById('edit-self-warning');
        const otherInfo = document.getElementById('edit-other-info');
        if (selfWarn) selfWarn.style.display = isSelf ? 'block' : 'none';
        if (otherInfo) otherInfo.style.display = isSelf ? 'none' : 'block';
        card.style.borderLeftColor = isSelf ? '#fbbf24' : '#FF6B00';
        card.style.background = isSelf ? '#fef9c3' : '#fff7ed';
      }
      window._adminEditSnapshot = {
        role: user.role,
        is_active: user.is_active !== false,
        must_change_password: Boolean(user.must_change_password),
        name: user.name,
        email: user.email,
        id: user.id,
      };
    } catch (error) { showToast(error.message, 'error'); }
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
    if (mode === 'edit' && window._adminEditSnapshot) {
      const snap = window._adminEditSnapshot;
      const changes = [];
      if (snap.role !== role) {
        const elevatedRoles = ['ADMIN', 'DIRECTOR', 'FINANCE'];
        const isElevation = elevatedRoles.includes(role) && !elevatedRoles.includes(snap.role);
        changes.push((isElevation ? '⚠ ELEVAR perfil' : 'Mudar perfil') + `: ${snap.role} → ${role}`);
      }
      if (snap.must_change_password !== payload.must_change_password) {
        changes.push(payload.must_change_password
          ? 'Forcar troca de senha no proximo login'
          : 'Remover obrigacao de trocar senha');
      }
      if (changes.length > 0) {
        const targetName = snap.name || snap.email || 'usuario';
        const lines = changes.map((c) => `  • ${c}`).join('\n');
        const ok = await confirmAction(`Voce esta prestes a alterar ${targetName}:\n\n${lines}\n\nConfirma?`);
        if (!ok) return;
      }
    }
    try {
      const url = mode === 'create' ? '/api/admin/users' : `/api/admin/users/${userId}`;
      const method = mode === 'create' ? 'POST' : 'PUT';
      await apiFetch(url, { method, body: JSON.stringify(payload) });
      showToast(mode === 'create' ? 'Usuario criado com sucesso!' : 'Alteracoes salvas.', 'success');
      setTimeout(() => { window.location.href = '/admin/users'; }, 1500);
    } catch (error) { showToast(error.message, 'error'); }
  }

  window.Economart.adminUsers = { initAdminUsers, initAdminUserForm };
  window.initAdminUsers = initAdminUsers;
  window.initAdminUserForm = initAdminUserForm;
})();
