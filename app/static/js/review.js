/* review.js — fluxo aprovacao gestor/diretor. */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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

  async function reviewInvoice(invoiceId, action, endpoint, directorId = null) {
    let comment = null;
    if (action !== 'APPROVE') {
      comment = await rejectReasonModal();
      if (!comment) return false;
    }
    try {
      const body = { action, comment };
      if (directorId) body.director_id = directorId;
      await apiFetch(endpoint, { method: 'POST', body: JSON.stringify(body) });
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
      const directorExtraHead = role === 'director' ? '<th scope="col">Gestor</th><th scope="col">Aprovado pelo Gestor em</th>' : '';
      container.innerHTML = `<table class="table"><caption class="sr-only">Fila de notas aguardando aprovacao</caption><thead><tr>
        <th scope="col">Funcionario</th><th scope="col">Setor</th><th scope="col">Numero da nota</th><th scope="col">Valor</th><th scope="col">Emissao</th><th scope="col">Vencimento</th><th scope="col">Dias ate vencer</th>${directorExtraHead}<th scope="col">Acoes</th>
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

  window.Economart.review = {
    initReviewQueue, initReviewDetail, reviewInvoice, rejectReasonModal,
  };
  window.initReviewQueue = initReviewQueue;
  window.initReviewDetail = initReviewDetail;
  window.reviewInvoice = reviewInvoice;
  window.rejectReasonModal = rejectReasonModal;
})();
