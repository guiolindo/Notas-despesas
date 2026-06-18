/* admin-departments.js — gestao de setores (admin). */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  window.Economart.adminDepartments = { initAdminDepartments };
  window.initAdminDepartments = initAdminDepartments;
})();
