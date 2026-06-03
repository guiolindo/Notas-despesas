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
  return String(value ?? '').replace(/[&<>"']/g, (char) => ({
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
