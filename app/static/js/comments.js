/* Modulo de comentarios da nota.
 *
 * Carregado DEPOIS de app.js — depende de window.Auth, window.apiFetch,
 * window.showToast, window.escapeHtml expostos por app.js e format.js.
 *
 * Exposicao via window.Economart.comments.* + aliases globais
 * (window.setupComments, window.renderComments) para compat com
 * callers em app.js que ainda usam o nome curto.
 *
 * Refator P2-1 v2 (auditoria). Mantem o mesmo comportamento, sem mexer
 * em paginacao, ordem de execucao ou Auth. */
(function () {
  'use strict';

  window.Economart = window.Economart || {};
  window.Economart.comments = window.Economart.comments || {};

  function _initials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/).filter(Boolean);
    const a = parts[0] && parts[0][0] ? parts[0][0] : '';
    const b = parts.length > 1 ? parts[parts.length - 1][0] : '';
    return (a + b).toUpperCase();
  }

  function _dateLabel(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso.endsWith('Z') || iso.includes('+') ? iso : iso + 'Z');
      return d.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
    } catch (e) {
      return iso;
    }
  }

  function render(items) {
    const thread = document.getElementById('comments-thread');
    const countEl = document.getElementById('comments-count');
    if (!thread) return;
    const Auth = window.Auth;
    const escapeHtml = window.escapeHtml || ((s) => String(s == null ? '' : s));
    const me = Auth ? Auth.getUser() : null;
    if (countEl) countEl.textContent = items.length ? `(${items.length})` : '';
    if (!items.length) {
      thread.innerHTML = '<p class="text-muted text-xs">Ainda nao ha comentarios. Use o campo abaixo pra perguntar ou esclarecer algo sem precisar reprovar a nota.</p>';
      return;
    }
    thread.innerHTML = items.map((c) => {
      const isMine = c.user && me && c.user.id === me.id;
      const author = c.user ? escapeHtml(c.user.name) : '(usuario removido)';
      const initials = escapeHtml(_initials(c.user && c.user.name));
      return `<div class="comment-item${isMine ? ' is-mine' : ''}">
        <span class="comment-avatar" title="${author}">${initials}</span>
        <div class="comment-body">
          <div class="comment-meta">
            <strong>${author}</strong>
            <span>${escapeHtml(_dateLabel(c.created_at))}</span>
          </div>
          <div class="comment-text">${escapeHtml(c.body)}</div>
        </div>
      </div>`;
    }).join('');
  }

  /** Backend pagina (P2-13 auditoria): GET /comments retorna
   *  { items, page, per_page, total, has_next }. Normalizamos pra
   *  { items, total } pra UI nao se importar com a paginacao no boot. */
  function _normalize(payload) {
    if (Array.isArray(payload)) return { items: payload, total: payload.length };
    return {
      items: (payload && payload.items) || [],
      total: (payload && payload.total) || 0
    };
  }

  async function setup(invoiceId) {
    const thread = document.getElementById('comments-thread');
    if (!thread) return;
    const apiFetch = window.apiFetch;
    const escapeHtml = window.escapeHtml || ((s) => String(s == null ? '' : s));
    const showToast = window.showToast || function () {};
    if (!apiFetch) {
      console.error('[comments] window.apiFetch indisponivel — app.js nao carregou?');
      return;
    }
    try {
      const data = _normalize(await apiFetch(`/api/invoices/${invoiceId}/comments`));
      render(data.items);
    } catch (e) {
      thread.innerHTML = `<p class="text-muted text-xs">Erro ao carregar comentarios: ${escapeHtml(e.message || '')}</p>`;
    }

    const input = document.getElementById('comments-input');
    const submit = document.getElementById('comments-submit');
    const form = document.getElementById('comments-form');
    if (!input || !submit || !form) return;
    input.addEventListener('input', () => {
      submit.disabled = input.value.trim().length === 0;
    });
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const body = input.value.trim();
      if (!body) return;
      submit.disabled = true;
      submit.textContent = 'Enviando...';
      try {
        await apiFetch(`/api/invoices/${invoiceId}/comments`, {
          method: 'POST',
          body: JSON.stringify({ body })
        });
        input.value = '';
        const data = _normalize(await apiFetch(`/api/invoices/${invoiceId}/comments`));
        render(data.items);
      } catch (err) {
        showToast((err && err.message) || 'Erro ao comentar.', 'error');
      } finally {
        submit.disabled = true;
        submit.textContent = 'Comentar';
      }
    });
  }

  // Namespace canonico.
  window.Economart.comments.setup = setup;
  window.Economart.comments.render = render;
  window.Economart.comments._normalize = _normalize;

  // Aliases globais para compat com callers em app.js.
  window.setupComments = setup;
  window.renderComments = render;
  window._normalizeCommentsResponse = _normalize;
})();
