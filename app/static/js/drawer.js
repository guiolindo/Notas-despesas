/* drawer.js — drawer lateral de invoice (compartilhado).
 * Depende de pdf-viewer.js, comments.js (setupDrawerComments).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

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
            <div class="section-header">
              <h2>Comentarios <span id="drawer-comments-count" class="text-muted text-xs"></span></h2>
            </div>
            <div id="drawer-comments-thread" class="comments-thread"></div>
            <form id="drawer-comments-form" class="comments-form" aria-label="Adicionar comentario">
              <textarea id="drawer-comments-input" rows="2" maxlength="2000" placeholder="Adicione um comentario..." aria-describedby="drawer-comments-help"></textarea>
              <div class="comments-form-footer">
                <small id="drawer-comments-help" class="text-muted text-xs">Maximo 2000 caracteres. Comentarios sao permanentes.</small>
                <button type="submit" id="drawer-comments-submit" class="btn btn-primary btn-sm" disabled>Comentar</button>
              </div>
            </form>
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
    const _dct = document.getElementById('drawer-comments-thread');
    if (_dct) _dct.innerHTML = '';
    const _dcc = document.getElementById('drawer-comments-count');
    if (_dcc) _dcc.textContent = '';
    const _dci = document.getElementById('drawer-comments-input');
    if (_dci) _dci.value = '';
    const _dcf = document.getElementById('drawer-comments-form');
    if (_dcf) delete _dcf.dataset.commentsBound;
    const pageLink = document.getElementById('drawer-open-page');
    pageLink.style.display = 'none';
    _drawerBackdrop.classList.add('open');
    _drawerEl.classList.add('open');
    try {
      const invoice = await apiFetch(`/api/invoices/${invoiceId}`);
      _renderDrawerContent(invoice);
      if (invoice.has_attachment) _loadDrawerPdf(invoiceId);
      if (window.setupDrawerComments) window.setupDrawerComments(invoiceId);
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
    renderAttachmentsBlock(invoice, '#drawer-pdf-panel');
    const _cc = invoice.comments_count || 0;
    const _commentsChip = _cc > 0
      ? ` <span class="status-badge" style="background:#fff3cd;color:#856404" title="${_cc} comentario${_cc === 1 ? '' : 's'} nesta nota">💬 ${_cc}</span>`
      : '';
    document.getElementById('drawer-status').innerHTML = statusBadge(invoice.status) + _commentsChip;
    const pageLink = document.getElementById('drawer-open-page');
    pageLink.href = `/invoices/${invoice.id}`;
    pageLink.style.display = '';
    const docLabel = invoice.supplier_document_type || 'CPF/CNPJ';
    const docFmt = invoice.supplier_document ? formatDocument(invoice.supplier_document) : '-';
    document.getElementById('drawer-grid').innerHTML = [
      ['Valor',          formatCurrency(invoice.amount)],
      ['Emissao',        formatDate(invoice.issue_date)],
      ['Vencimento',     formatDate(invoice.due_date)],
      ['Setor',          invoice.department_name || '-'],
      [docLabel,         docFmt],
      ['Fornecedor',     invoice.supplier_name || '-'],
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
    const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Cancelada', APPROVED_MANAGER: 'Aprovada gestor', REJECTED_MANAGER: 'Reprovada gestor', APPROVED_DIRECTOR: 'Aprovada diretor', REJECTED_DIRECTOR: 'Reprovada diretor', MARKED_PAID: 'Lancada', PRINTED: 'Comprovante impresso', TRANSFERRED_DIRECTOR: 'Repasse de diretor' };
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
    if (role === 'MANAGER' && invoice.status === 'AGUARDANDO_GESTOR') return _renderDrawerManagerReview(invoice);
    if (role === 'DIRECTOR' && invoice.status === 'AGUARDANDO_DIRETOR') return _renderDrawerDirectorReview(invoice);
    if (role === 'FINANCE' && (invoice.status === 'APROVADO' || invoice.status === 'PAGO')) return _renderDrawerFinance(invoice);

    const actionsEl = document.getElementById('drawer-actions');
    const isDirect = Boolean(user?.submit_directly_to_director);
    const buttons = [];
    if (invoice.can_cancel) buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
    if (invoice.status === 'RASCUNHO') {
      buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
      buttons.push(isDirect
        ? '<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>'
        : '<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
      buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
    }
    if (invoice.status.startsWith('REPROVADO')) {
      buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
      buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
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
            const updated = await submitInvoiceWithDuplicateCheck(invoice.id);
            if (!updated) return;
            showToast('Nota enviada para o gestor.', 'success');
            _refreshAfterAction();
          } else if (btn.dataset.action === 'submit-direct') {
            const dirId = document.getElementById('drawer-dir-chosen')?.value;
            if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
            const updated = await submitInvoiceWithDuplicateCheck(invoice.id, dirId);
            if (!updated) return;
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
        <button class="btn btn-ghost" id="drawer-dir-show-transfer">Repassar a outro diretor</button>
      </div>
      <div id="drawer-dir-reject-sec" class="hidden" style="margin-top:1rem">
        <label class="form-label">Motivo da reprovacao (obrigatorio)</label>
        <textarea id="drawer-dir-reject-txt" class="form-input" rows="3" maxlength="500" placeholder="Minimo 10 caracteres..."></textarea>
        <div class="review-actions" style="margin-top:.5rem">
          <button class="btn btn-danger" id="drawer-dir-confirm-reject" disabled>Confirmar reprovacao</button>
          <button class="btn btn-ghost" id="drawer-dir-cancel-reject">Cancelar</button>
        </div>
      </div>
      <div id="drawer-dir-transfer-sec" class="hidden" style="margin-top:1rem">
        <label class="form-label">Repassar para outro diretor</label>
        <p class="text-muted text-xs">A nota muda de mao mantendo o status aguardando diretor.</p>
        <div id="drawer-dir-transfer-list" class="director-list"><p class="text-muted">Carregando diretores...</p></div>
        <input type="hidden" id="drawer-dir-transfer-target">
        <label class="form-label" style="margin-top:.75rem">Motivo do repasse (minimo 10 caracteres)</label>
        <textarea id="drawer-dir-transfer-txt" class="form-input" rows="3" maxlength="500" placeholder="Ex: nota e de outro setor / conflito de interesse..."></textarea>
        <div class="review-actions" style="margin-top:.5rem">
          <button class="btn btn-primary" id="drawer-dir-confirm-transfer" disabled>Confirmar repasse</button>
          <button class="btn btn-ghost" id="drawer-dir-cancel-transfer">Cancelar</button>
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
    document.getElementById('drawer-dir-show-transfer').addEventListener('click', async () => {
      document.getElementById('drawer-dir-transfer-sec').classList.remove('hidden');
      try {
        const directors = await apiFetch('/api/invoices/directors');
        const me = Auth.getUser();
        const others = directors.filter((d) => d.id !== me?.id && d.is_active && !d.unavailable_for_notes);
        renderDirectorList(others, 'drawer-dir-transfer-list', 'drawer-dir-transfer-target');
      } catch (e) {
        document.getElementById('drawer-dir-transfer-list').innerHTML =
          '<p class="text-muted">Nao foi possivel carregar a lista. Tente novamente.</p>';
      }
      const txt = document.getElementById('drawer-dir-transfer-txt');
      const btn = document.getElementById('drawer-dir-confirm-transfer');
      const targetField = document.getElementById('drawer-dir-transfer-target');
      function updateBtn() {
        btn.disabled = !(txt.value.trim().length >= 10 && targetField.value);
      }
      txt.addEventListener('input', updateBtn);
      targetField.addEventListener('change', updateBtn);
      document.getElementById('drawer-dir-transfer-list').addEventListener('click', () => setTimeout(updateBtn, 0));
    });
    document.getElementById('drawer-dir-cancel-transfer').addEventListener('click', () => {
      document.getElementById('drawer-dir-transfer-sec').classList.add('hidden');
    });
    document.getElementById('drawer-dir-confirm-transfer').addEventListener('click', async () => {
      const newId = document.getElementById('drawer-dir-transfer-target').value;
      const comment = document.getElementById('drawer-dir-transfer-txt').value.trim();
      try {
        await apiFetch(`/api/invoices/${invoice.id}/transfer-director`, {
          method: 'POST',
          body: JSON.stringify({ new_director_id: newId, comment }),
        });
        showToast('Nota repassada com sucesso.', 'success');
        _refreshAfterAction();
      } catch (e) { showToast(e.message, 'error'); }
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
    document.getElementById('drawer-finance-print').addEventListener('click', async (ev) => {
      if (!isReprint && !(await confirmAction(`Confirmar lancamento da nota ${invoice.invoice_number}? Esta acao sera registrada e nao pode ser desfeita.`))) return;
      const loadingTxt = isReprint ? 'Gerando comprovante...' : 'Lancando...';
      await withButtonLoading(ev.currentTarget, loadingTxt, async () => {
        const { url, method } = _printOrMarkPaidEndpoint(invoice);
        const ok = await fetchAndOpenPdf(url, { method });
        if (ok) {
          showToast(isReprint ? 'Comprovante reimpresso.' : 'Comprovante gerado. Nota lancada.', 'success');
          setTimeout(async () => {
            const updated = await apiFetch(`/api/invoices/${invoice.id}`);
            _renderDrawerContent(updated);
            if (updated.has_attachment) _loadDrawerPdf(invoice.id);
          }, 1200);
        }
      });
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

  window.Economart.drawer = { openInvoiceDrawer, closeDrawer };
  window.openInvoiceDrawer = openInvoiceDrawer;
  window.closeDrawer = closeDrawer;
})();
