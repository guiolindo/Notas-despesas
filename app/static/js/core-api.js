/* core-api.js — apiFetch + submitInvoiceWithDuplicateCheck.
 *
 * Depende de window.Auth (core-auth.js).
 * Outros modulos usam window.apiFetch.
 *
 * P2-1 v3 (auditoria, jun/2026): split do core.js (Fase 3).
 */
(function () {
  'use strict';
  if (typeof window === 'undefined') return;
  window.Economart = window.Economart || {};

  async function apiFetch(url, options = {}) {
    const headers = new Headers(options.headers || {});
    if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    let token = Auth.getToken();
    if (!token) token = await Auth.ensureToken();
    if (token) headers.set('Authorization', `Bearer ${token}`);

    let response;
    try {
      response = await fetch(url, { ...options, headers, credentials: 'include' });
      window.dispatchEvent(new CustomEvent('app:network-ok'));
    } catch (netErr) {
      window.dispatchEvent(new CustomEvent('app:network-error'));
      const err = new Error('Sem conexao com o servidor. Verifique sua internet.');
      err.networkError = true;
      err.cause = netErr;
      throw err;
    }
    if (response.status === 401) {
      const newToken = await Auth.ensureToken();
      if (newToken && newToken !== token) {
        headers.set('Authorization', `Bearer ${newToken}`);
        response = await fetch(url, { ...options, headers, credentials: 'include' });
      }
      if (response.status === 401) {
        Auth.clear();
        window.location.href = '/login';
        throw new Error('Sessao expirada');
      }
    }
    if (response.status === 428) {
      if (window.location.pathname !== '/change-password') {
        window.location.href = '/change-password';
      }
      throw new Error('Troca de senha obrigatoria antes de continuar.');
    }
    const contentType = response.headers.get('content-type') || '';
    const data = contentType.includes('application/json') ? await response.json() : await response.text();
    if (!response.ok) {
      if (response.status >= 500) {
        console.error('[apiFetch] 5xx:', response.status, data);
        throw new Error('Erro no servidor. Tente novamente em alguns segundos.');
      }
      if (Array.isArray(data?.detail)) {
        const first = data.detail[0];
        const field = Array.isArray(first?.loc) ? first.loc[first.loc.length - 1] : '';
        throw new Error(field ? `${field}: ${first.msg}` : (first?.msg || 'Dados invalidos'));
      }
      if (response.status === 409 && data?.detail && typeof data.detail === 'object') {
        const err = new Error(data.detail.message || 'Conflito de duplicidade');
        err.code = data.detail.code;
        err.data = data.detail;
        err.status = 409;
        throw err;
      }
      throw new Error(data?.detail || (typeof data === 'string' ? data : null) || 'Erro na requisicao');
    }
    return data;
  }

  async function submitInvoiceWithDuplicateCheck(invoiceId, directorId = null) {
    const base = `/api/invoices/${invoiceId}/submit`;
    const query = new URLSearchParams();
    if (directorId) query.set('director_id', directorId);
    try {
      return await apiFetch(`${base}?${query.toString()}`, { method: 'POST' });
    } catch (err) {
      if (err.code !== 'DUPLICATE_INVOICE_NUMBER') throw err;
      const ok = await confirmAction(
        `${err.data?.message || 'Nota duplicada detectada.'}\n\nDeseja enviar mesmo assim?`,
      );
      if (!ok) return null;
      query.set('confirm_duplicate', 'true');
      return apiFetch(`${base}?${query.toString()}`, { method: 'POST' });
    }
  }

  window.Economart.core = window.Economart.core || {};
  window.Economart.core.apiFetch = apiFetch;
  window.Economart.core.submitInvoiceWithDuplicateCheck = submitInvoiceWithDuplicateCheck;
  window.apiFetch = apiFetch;
  window.submitInvoiceWithDuplicateCheck = submitInvoiceWithDuplicateCheck;
})();
