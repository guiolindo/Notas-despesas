/* pdf-viewer.js — fetchAndOpenPdf, viewer inline, director picker.
 * Depende de window.Auth, window.apiFetch, window.showToast, window.escapeHtml.
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  async function fetchAndOpenPdf(url, options = {}) {
    // POST /mark-paid e GET /print sao diferenciados via options.method.
    const method = (options.method || 'GET').toUpperCase();
    showLoading();
    try {
      const token = Auth.getToken();
      const headers = token ? { Authorization: `Bearer ${token}` } : {};
      const resp = await fetch(url, { method, headers });
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

  function _printOrMarkPaidEndpoint(invoice) {
    if (invoice.status === 'APROVADO') {
      return { url: `/api/invoices/${invoice.id}/mark-paid`, method: 'POST' };
    }
    return { url: `/api/invoices/${invoice.id}/print`, method: 'GET' };
  }

  let _pdfViewerState = { zoom: 1 };

  function _applyPdfTransform() {
    const iframe = document.getElementById('pdf-iframe');
    if (!iframe) return;
    iframe.style.transform = `scale(${_pdfViewerState.zoom})`;
    const label = document.getElementById('pdf-zoom-label');
    if (label) label.textContent = `${Math.round(_pdfViewerState.zoom * 100)}%`;
  }

  function _setupPdfToolbar() {
    const panel = document.getElementById('pdf-panel');
    if (!panel || panel.dataset.toolbarReady) return;
    panel.dataset.toolbarReady = '1';
    document.getElementById('pdf-zoom-in')?.addEventListener('click', () => {
      _pdfViewerState.zoom = Math.min(_pdfViewerState.zoom + 0.1, 3);
      _applyPdfTransform();
    });
    document.getElementById('pdf-zoom-out')?.addEventListener('click', () => {
      _pdfViewerState.zoom = Math.max(_pdfViewerState.zoom - 0.1, 0.4);
      _applyPdfTransform();
    });
    document.getElementById('pdf-fullscreen')?.addEventListener('click', () => {
      panel.classList.toggle('fullscreen');
    });
  }

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
      _pdfViewerState = { zoom: 1 };
      _applyPdfTransform();
      _setupPdfToolbar();
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

  window.Economart.pdfViewer = {
    fetchAndOpenPdf, _printOrMarkPaidEndpoint, loadPdfInline,
    renderDirectorList, pickDirectorModal,
  };
  window.fetchAndOpenPdf = fetchAndOpenPdf;
  window._printOrMarkPaidEndpoint = _printOrMarkPaidEndpoint;
  window.loadPdfInline = loadPdfInline;
  window.renderDirectorList = renderDirectorList;
  window.pickDirectorModal = pickDirectorModal;
})();
