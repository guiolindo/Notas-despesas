/* invoice-form.js — criar/editar nota (form). */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  function setupSupplierDocField() {
    const input = document.getElementById('supplier-document');
    const status = document.getElementById('supplier-doc-status');
    const nameInput = document.getElementById('supplier-name');
    const legalNameInput = document.getElementById('supplier-legal-name');
    if (!input) return;
    let debounce = null;
    const update = async () => {
      const raw = input.value;
      const digits = stripDocDigits(raw);
      if (digits.length <= 14) input.value = formatDocument(digits);
      if (digits.length === 11) {
        if (validateCPF(digits)) {
          status.textContent = 'CPF valido.';
          status.style.color = 'var(--success)';
        } else {
          status.textContent = 'CPF invalido. Verifique os digitos.';
          status.style.color = 'var(--error)';
        }
      } else if (digits.length === 14) {
        if (validateCNPJ(digits)) {
          status.textContent = 'CNPJ valido. Buscando nome...';
          status.style.color = 'var(--success)';
          clearTimeout(debounce);
          debounce = setTimeout(async () => {
            try {
              const data = await apiFetch(`/api/invoices/lookup-cnpj/${digits}`);
              if (data?.razao_social || data?.nome_fantasia) {
                nameInput.value = data.nome_fantasia || data.razao_social || '';
                legalNameInput.value = data.razao_social || '';
                status.textContent = 'CNPJ valido. Dados do fornecedor preenchidos.';
              } else {
                status.textContent = 'CNPJ valido. Nao localizamos a razao social — preencha manualmente.';
              }
            } catch (e) {
              status.textContent = 'CNPJ valido. Nao foi possivel buscar a razao social agora — preencha manualmente.';
              status.style.color = 'var(--warning)';
            }
          }, 400);
        } else {
          status.textContent = 'CNPJ invalido. Verifique os digitos.';
          status.style.color = 'var(--error)';
        }
      } else if (digits.length === 0) {
        status.textContent = 'Digite o CPF (11) ou CNPJ (14).';
        status.style.color = 'var(--text-muted)';
      } else {
        status.textContent = `Faltam ${digits.length < 11 ? 11 - digits.length : 14 - digits.length} digitos.`;
        status.style.color = 'var(--text-muted)';
      }
    };
    input.addEventListener('input', update);
  }

  function setupInvoiceFileInput() {
    const dropZone = document.getElementById('drop-zone');
    const input = document.getElementById('invoice-file');
    const label = document.getElementById('selected-file-name');
    if (!dropZone || !input) return;
    const MAX_FILES = 5;
    const updateName = () => {
      const files = Array.from(input.files || []);
      if (!files.length) { label.textContent = 'Nenhum arquivo selecionado'; return; }
      if (files.length === 1) label.textContent = files[0].name;
      else label.textContent = `${files.length} arquivos: ${files.map(f => f.name).join(', ')}`;
    };
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
      const dropped = Array.from(event.dataTransfer.files || []);
      const pdfs = dropped.filter((f) =>
        f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf')
      );
      if (!pdfs.length) { showToast('Selecione arquivos PDF.', 'error'); return; }
      if (pdfs.length > MAX_FILES) {
        showToast(`Maximo ${MAX_FILES} arquivos por nota.`, 'error');
        return;
      }
      const transfer = new DataTransfer();
      pdfs.forEach((f) => transfer.items.add(f));
      input.files = transfer.files;
      updateName();
    });
    input.addEventListener('change', () => {
      if ((input.files?.length || 0) > MAX_FILES) {
        showToast(`Maximo ${MAX_FILES} arquivos. Selecione menos.`, 'error');
        input.value = '';
      }
      updateName();
    });
  }

  async function initInvoiceForm(mode) {
    const description = document.getElementById('description');
    description?.addEventListener('input', () => {
      document.getElementById('description-count').textContent = description.value.length;
    });
    setupInvoiceFileInput();
    setupSupplierDocField();
    const user = Auth.getUser();
    if (user?.role === 'DIRECTOR') {
      const submitBtn = document.getElementById('invoice-submit-btn');
      if (submitBtn) submitBtn.textContent = 'Criar e Enviar ao Financeiro';
    } else if (user?.submit_directly_to_director || user?.role === 'MANAGER') {
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
    const docInput = document.getElementById('supplier-document');
    if (docInput && invoice.supplier_document) {
      docInput.value = formatDocument(invoice.supplier_document);
      docInput.dispatchEvent(new Event('input'));
    }
    const nameInput = document.getElementById('supplier-name');
    const legalInput = document.getElementById('supplier-legal-name');
    if (nameInput) nameInput.value = invoice.supplier_name || '';
    if (legalInput) legalInput.value = invoice.supplier_legal_name || '';
    renderExistingAttachmentsList(invoice);
  }

  function renderExistingAttachmentsList(invoice) {
    const group = document.getElementById('existing-attachments-group');
    const list = document.getElementById('existing-attachments-list');
    if (!group || !list) return;
    const attachments = invoice.attachments || [];
    if (!attachments.length) { group.classList.add('hidden'); return; }
    group.classList.remove('hidden');
    list.innerHTML = attachments.map((att) => {
      const sizeKb = (att.size_bytes / 1024).toFixed(0);
      const canRemove = attachments.length > 1;
      return `<div class="attachment-row">
        <a href="/api/invoices/${escapeHtml(invoice.id)}/attachments/${escapeHtml(att.id)}" target="_blank" rel="noopener">
          ${escapeHtml(att.drive_file_name || 'anexo.pdf')}
        </a>
        <span class="text-muted" style="font-size:.8rem">${sizeKb} KB</span>
        ${canRemove ? `<button type="button" class="btn btn-ghost btn-sm" data-remove-attachment="${escapeHtml(att.id)}">Remover</button>` : ''}
      </div>`;
    }).join('');
    list.querySelectorAll('[data-remove-attachment]').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const attId = btn.dataset.removeAttachment;
        if (!(await confirmAction('Remover este anexo?'))) return;
        try {
          await apiFetch(`/api/invoices/${invoice.id}/attachments/${attId}`, { method: 'DELETE' });
          showToast('Anexo removido.', 'success');
          const fresh = await apiFetch(`/api/invoices/${invoice.id}`);
          renderExistingAttachmentsList(fresh);
        } catch (e) { showToast(e.message, 'error'); }
      });
    });
  }

  async function saveInvoice(event, mode, submitNow = true) {
    if (event) event.preventDefault();
    const issueDate = document.getElementById('issue-date').value;
    const dueDate = document.getElementById('due-date').value;
    const description = document.getElementById('description').value.trim();
    const supplierDocRaw = document.getElementById('supplier-document')?.value || '';
    const supplierDoc = stripDocDigits(supplierDocRaw);
    const filesInput = document.getElementById('invoice-file');
    const files = Array.from(filesInput?.files || []);
    if (dueDate < issueDate) return showToast('Vencimento nao pode ser anterior a emissao.', 'error');
    if (description.length < 10) return showToast('Descricao deve ter ao menos 10 caracteres.', 'error');
    if (!supplierDoc) return showToast('Informe o CPF ou CNPJ do fornecedor.', 'error');
    const isValidDoc = supplierDoc.length === 11 ? validateCPF(supplierDoc) :
                       supplierDoc.length === 14 ? validateCNPJ(supplierDoc) : false;
    if (!isValidDoc) return showToast('CPF/CNPJ invalido. Verifique os digitos.', 'error');
    const invalidFile = files.find((f) => !f.name.toLowerCase().endsWith('.pdf'));
    if (invalidFile) return showToast(`'${invalidFile.name}' nao e um PDF.`, 'error');
    if (mode !== 'edit' && files.length === 0) {
      return showToast('Anexe ao menos um PDF (nota fiscal) antes de continuar.', 'error');
    }
    if (files.length > 5) return showToast('Maximo 5 arquivos por nota.', 'error');
    const form = new FormData();
    form.append('invoice_number', document.getElementById('invoice-number').value.trim());
    form.append('amount', document.getElementById('amount').value);
    form.append('issue_date', issueDate);
    form.append('due_date', dueDate);
    form.append('description', description);
    form.append('bank_details', document.getElementById('bank-details').value.trim());
    form.append('supplier_document', supplierDoc);
    form.append('supplier_name', document.getElementById('supplier-name')?.value?.trim() || '');
    form.append('supplier_legal_name', document.getElementById('supplier-legal-name')?.value?.trim() || '');
    files.forEach((f) => form.append('files', f));
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

  window.Economart.invoiceForm = { initInvoiceForm };
  window.initInvoiceForm = initInvoiceForm;
})();
