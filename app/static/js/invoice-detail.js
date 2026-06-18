/* invoice-detail.js — pagina de detalhe de nota (/invoices/<id>).
 * Depende de pdf-viewer.js (fetchAndOpenPdf, loadPdfInline, renderDirectorList),
 * comments.js (setupComments), e dos helpers globais.
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  async function initInvoiceDetail() {
    const invoiceId = getInvoiceIdFromPath();
    const invoice = await apiFetch(invoiceApiPath(invoiceId));
    renderInvoiceDetail(invoice);
    if (invoice.has_attachment) loadPdfInline(invoiceId);
    if (window.setupComments) window.setupComments(invoiceId);
  }

  function renderInvoiceAlerts(invoice, containerId) {
    const target = document.getElementById(containerId);
    if (!target) return;
    const alertsId = `${containerId}-alerts-banner`;
    let banner = document.getElementById(alertsId);
    const items = invoice?.alerts || [];
    if (!items.length) { if (banner) banner.remove(); return; }
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

  function renderAttachmentsBlock(/* invoice, targetSelector */) {
    // No-op: multi-anexo agora e mesclado pelo backend em PDF unico.
  }

  function renderInvoiceDetail(invoice) {
    document.getElementById('detail-title').textContent = `Nota ${invoice.invoice_number}`;
    document.getElementById('detail-subtitle').textContent = `Criada por ${invoice.created_by.name} em ${formatDateTime(invoice.created_at)}`;
    document.getElementById('detail-status').innerHTML = statusBadge(invoice.status);
    renderInvoiceAlerts(invoice, 'detail-grid');
    renderAttachmentsBlock(invoice, '#pdf-panel');
    const docLabel = invoice.supplier_document_type || 'CPF/CNPJ';
    const docFormatted = invoice.supplier_document ? formatDocument(invoice.supplier_document) : '-';
    const supplierLine = invoice.supplier_name
      ? `${invoice.supplier_name}${invoice.supplier_legal_name && invoice.supplier_legal_name !== invoice.supplier_name ? ` (${invoice.supplier_legal_name})` : ''}`
      : '-';
    document.getElementById('detail-grid').innerHTML = [
      ['Valor', formatCurrency(invoice.amount)], ['Emissao', formatDate(invoice.issue_date)],
      ['Vencimento', formatDate(invoice.due_date)], ['Criador', invoice.created_by.name],
      ['Setor', invoice.department_name || '-'],
      [docLabel, docFormatted], ['Fornecedor', supplierLine],
      ['Descricao', invoice.description],
      ['Dados bancarios', invoice.bank_details || '-']
    ].map(([label, value]) => `<div class="detail-item"><span>${label}</span><strong>${escapeHtml(String(value))}</strong></div>`).join('');
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
    if (invoice.can_cancel) buttons.push('<button class="btn btn-ghost" data-action="cancel">Cancelar nota</button>');
    if (invoice.status === 'RASCUNHO') {
      buttons.push(`<a class="btn btn-ghost" href="/invoices/${invoice.id}/edit">Editar</a>`);
      if (isDirect) buttons.push('<button class="btn btn-primary" data-action="submit-direct">Enviar para Diretor</button>');
      else buttons.push('<button class="btn btn-primary" data-action="submit">Enviar para Gestor</button>');
      buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
    }
    if (invoice.status.startsWith('REPROVADO')) {
      buttons.push(`<a class="btn btn-primary" href="/invoices/${invoice.id}/edit">Editar e Reenviar</a>`);
      buttons.push('<button class="btn btn-danger" data-action="delete">Excluir</button>');
    }
    if (invoice.status === 'PAGO' && ['CONTAS_A_PAGAR', 'FINANCE', 'ADMIN'].includes(user?.role)) {
      buttons.push('<button class="btn btn-primary" data-action="reprint">Reimprimir comprovante</button>');
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
            const updated = await submitInvoiceWithDuplicateCheck(invoice.id);
            if (!updated) return;
            showToast('Nota enviada para o gestor.', 'success');
            renderInvoiceDetail(updated);
            if (updated.has_attachment) loadPdfInline(updated.id);
          } else if (button.dataset.action === 'submit-direct') {
            const dirId = document.getElementById('detail-chosen-director')?.value;
            if (!dirId) { showToast('Selecione um diretor.', 'error'); return; }
            const updated = await submitInvoiceWithDuplicateCheck(invoice.id, dirId);
            if (!updated) return;
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
          } else if (button.dataset.action === 'reprint') {
            const ok = await fetchAndOpenPdf(`/api/invoices/${invoice.id}/print`);
            if (ok) showToast('Comprovante gerado.', 'success');
          }
        } catch (e) { showToast(e.message, 'error'); }
      });
    });
  }

  function renderTimeline(history) {
    const icons = { CREATED: '+', SUBMITTED: '>', APPROVED_MANAGER: '✓', REJECTED_MANAGER: 'x', APPROVED_DIRECTOR: '✓', REJECTED_DIRECTOR: 'x', MARKED_PAID: '$' };
    const labels = { CREATED: 'Criada', SUBMITTED: 'Enviada', CANCELLED: 'Envio cancelado', APPROVED_MANAGER: 'Aprovada pelo gestor', REJECTED_MANAGER: 'Reprovada pelo gestor', APPROVED_DIRECTOR: 'Aprovada pelo diretor', REJECTED_DIRECTOR: 'Reprovada pelo diretor', MARKED_PAID: 'Marcada como lancada', PRINTED: 'Impressa', TRANSFERRED_DIRECTOR: 'Repassada a outro diretor' };
    const el = document.getElementById('invoice-timeline');
    if (!el) return;
    el.innerHTML = history.map((item) => `
      <div class="timeline-item"><div class="timeline-icon">${icons[item.action] || '-'}</div><div>
        <strong>${labels[item.action] || item.action}</strong>
        <div class="timeline-meta">${escapeHtml(item.user.name)} - ${formatDateTime(item.timestamp)}</div>
        ${item.comment ? `<p>${escapeHtml(item.comment)}</p>` : ''}
      </div></div>`).join('');
  }

  window.Economart.invoiceDetail = {
    initInvoiceDetail, renderInvoiceDetail, renderInvoiceAlerts,
    renderAttachmentsBlock, renderDetailActions, renderTimeline,
  };
  window.initInvoiceDetail = initInvoiceDetail;
  window.renderInvoiceDetail = renderInvoiceDetail;
  window.renderInvoiceAlerts = renderInvoiceAlerts;
  window.renderAttachmentsBlock = renderAttachmentsBlock;
  window.renderTimeline = renderTimeline;
})();
