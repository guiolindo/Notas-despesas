/* Helpers de formatacao PUROS. Sem dependencia de Auth ou rede.
 *
 * Carregado ANTES de app.js (precisa estar pronto para todas as funcoes
 * declaradas em app.js que usam formatDate, escapeHtml etc).
 *
 * Exposicao via window.Economart.format.* (namespace) E aliases
 * window.formatDate, window.escapeHtml etc. (compatibilidade com callers
 * historicos espalhados em app.js — migracao incremental).
 *
 * Refator P2-1 v2 (auditoria). Versao anterior (commit 2b3c105) foi
 * revertida; esta repete o split mas com:
 *  - namespace consistente (Economart.format).
 *  - aliases explicitos pra compat.
 *  - documentacao das dependencias.
 *  - smoke runtime documentado em tests/manual-smoke.md. */
(function () {
  'use strict';

  window.Economart = window.Economart || {};
  window.Economart.format = window.Economart.format || {};

  const TZ = 'America/Sao_Paulo';

  function formatDate(dateStr) {
    if (!dateStr) return '-';
    return new Intl.DateTimeFormat('pt-BR', { timeZone: 'UTC' }).format(new Date(`${dateStr}T00:00:00Z`));
  }

  function formatDateTime(dateStr) {
    if (!dateStr) return '-';
    return new Intl.DateTimeFormat('pt-BR', {
      timeZone: TZ,
      dateStyle: 'short',
      timeStyle: 'short'
    }).format(new Date(dateStr));
  }

  /** Retorna a hora atual no fuso horario de Brasilia (0-23). */
  function hourInBR() {
    return parseInt(new Intl.DateTimeFormat('en-US', { timeZone: TZ, hour: 'numeric', hour12: false }).format(new Date()), 10);
  }

  /** Retorna a string YYYY-MM-DD de hoje em Brasilia. */
  function todayInBR() {
    return new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date());
  }

  function formatCurrency(value) {
    return new Intl.NumberFormat('pt-BR', {
      style: 'currency',
      currency: 'BRL'
    }).format(Number(value || 0));
  }

  function escapeHtml(value) {
    return String(value === undefined || value === null ? '' : value).replace(/[&<>"']/g, (char) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    })[char]);
  }

  function statusBadge(status) {
    const text = {
      RASCUNHO: 'Rascunho',
      AGUARDANDO_GESTOR: 'Aguardando gestor',
      REPROVADO_GESTOR: 'Reprovado gestor',
      AGUARDANDO_DIRETOR: 'Aguardando diretor',
      REPROVADO_DIRETOR: 'Reprovado diretor',
      APROVADO: 'Aprovado',
      PAGO: 'Lancado'
    }[status] || status;
    return `<span class="status-badge status-${String(status).toLowerCase()}">${text}</span>`;
  }

  // Namespace canonico.
  window.Economart.format.TZ = TZ;
  window.Economart.format.formatDate = formatDate;
  window.Economart.format.formatDateTime = formatDateTime;
  window.Economart.format.hourInBR = hourInBR;
  window.Economart.format.todayInBR = todayInBR;
  window.Economart.format.formatCurrency = formatCurrency;
  window.Economart.format.escapeHtml = escapeHtml;
  window.Economart.format.statusBadge = statusBadge;

  // Aliases globais para compatibilidade com callers em app.js. Apos
  // migrar todos os callers para Economart.format.*, removemos estes.
  window.TZ = TZ;
  window.formatDate = formatDate;
  window.formatDateTime = formatDateTime;
  window.hourInBR = hourInBR;
  window.todayInBR = todayInBR;
  window.formatCurrency = formatCurrency;
  window.escapeHtml = escapeHtml;
  window.statusBadge = statusBadge;
})();
