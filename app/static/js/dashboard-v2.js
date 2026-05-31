/* ============================================================================
   dashboard-v2.js — lógica do dashboard refeito (refresh visual).
   Isolado de app.js. Carregado APENAS em /dashboard.

   Responsabilidades:
     1. Hidratar contadores (review queue, minhas notas, conferidas hoje)
     2. Renderizar lista de alertas por perfil (consumindo /api/alerts)
     3. Popular a tabela de notas recentes (/api/invoices?limit=5)
     4. Atalho de teclado F2 → abrir scanner (perfil CONTAS_A_PAGAR)
     5. Saudação contextual por horário de Brasília

   NÃO mexe em nada que app.js já gerencia.
   ============================================================================ */
(function () {
  'use strict';

  // ─── Helpers ────────────────────────────────────────────────────────
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));

  const fmtBRL = (v) => new Intl.NumberFormat('pt-BR', {
    style: 'currency', currency: 'BRL',
  }).format(Number(v || 0));

  const fmtDate = (iso) => {
    if (!iso) return '—';
    const [y, m, d] = iso.slice(0, 10).split('-');
    return `${d}/${m}/${y}`;
  };

  const STATUS_LABELS = {
    RASCUNHO: 'Rascunho',
    AGUARDANDO_GESTOR: 'Aguardando gestor',
    REPROVADO_GESTOR: 'Reprovado gestor',
    AGUARDANDO_DIRETOR: 'Aguardando diretor',
    REPROVADO_DIRETOR: 'Reprovado diretor',
    APROVADO: 'Aprovado',
    PAGO: 'Lançada',
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function statusBadgeHtml(status) {
    const label = STATUS_LABELS[status] || status || '—';
    const cls = 'status-' + String(status || '').toLowerCase();
    return `<span class="status-badge ${cls}">${escapeHtml(label)}</span>`;
  }

  // ─── Saudação por horário de Brasília ────────────────────────────────
  function setGreeting() {
    const greetEl = $('#dashboard-greeting');
    if (!greetEl) return;
    const txt = greetEl.textContent.trim();
    const first = txt.replace(/^(Olá|Bom dia|Boa tarde|Boa noite),?\s*/i, '');
    const brt = new Date(new Date().toLocaleString('en-US', { timeZone: 'America/Sao_Paulo' }));
    const h = brt.getHours();
    const prefix = h < 12 ? 'Bom dia' : (h < 18 ? 'Boa tarde' : 'Boa noite');
    greetEl.textContent = `${prefix}, ${first}`;
  }

  // ─── Atalho F2 (CONTAS_A_PAGAR) ─────────────────────────────────────
  function bindScannerShortcut() {
    const link = $('#qa-open-scanner');
    if (!link) return; // só registra se o hero do scanner existe
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'F2') return;
      const tag = (e.target && e.target.tagName) || '';
      // Não roube o atalho de inputs/textareas/contenteditables
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.target && e.target.isContentEditable) return;
      e.preventDefault();
      window.location.href = link.href;
    });
  }

  // ─── Render: alertas (CONTAS_A_PAGAR) ───────────────────────────────
  function renderAlertsCap(alerts) {
    const root = $('#dashboard-alerts-cap');
    if (!root) return;
    const out = [];

    const overdue = (alerts.overdue || []).length;
    const due72 = (alerts.due_72h || []).length;
    const oldEm = (alerts.old_emission || []).length;

    if (overdue > 0) out.push(rowHtml('ar-err', 'icon-circle-alert',
      `${overdue} notas vencidas a conferir`,
      'Bucket overdue', '/alerts?bucket=overdue'));
    if (due72 > 0) out.push(rowHtml('ar-warn', 'icon-clock',
      `${due72} notas vencem em até 72 h`,
      'Bucket due_72h', '/alerts?bucket=due_72h'));
    if (oldEm > 0) out.push(rowHtml('ar-info', 'icon-calendar',
      `${oldEm} notas com emissão do mês anterior`,
      'Bucket old_emission · confirme prazo de lançamento',
      '/alerts?bucket=old_emission'));

    if (!out.length) out.push(emptyHtml());
    root.innerHTML = out.join('');
  }

  // ─── Render: alertas (aprovadores) ───────────────────────────────────
  function renderAlertsApprover(alerts) {
    const root = $('#dashboard-alerts-approver');
    if (!root) return;
    const out = [];

    const pending = (alerts.pending_review || []).length;
    const overdue = (alerts.overdue || []).length;
    const due72 = (alerts.due_72h || []).length;
    const rejected = (alerts.rejected || []).length;

    if (pending > 0) out.push(rowHtml('ar-blue', 'icon-activity',
      `${pending} notas aguardando sua aprovação`,
      'Bucket pending_review · ordenadas por submitted_at',
      '/manager/queue'));
    if (overdue > 0) out.push(rowHtml('ar-err', 'icon-circle-alert',
      `${overdue} notas vencidas`,
      'Bucket overdue', '/alerts?bucket=overdue'));
    if (due72 > 0) out.push(rowHtml('ar-warn', 'icon-clock',
      `${due72} notas vencem em até 72 h`,
      'Bucket due_72h', '/alerts?bucket=due_72h'));
    if (rejected > 0) out.push(rowHtml('ar-err', 'icon-x',
      `${rejected} das suas notas foram reprovadas`,
      'Bucket rejected (só para o criador) · corrija e reenvie',
      '/invoices?status=REPROVADO_GESTOR'));

    if (!out.length) out.push(emptyHtml());
    root.innerHTML = out.join('');
  }

  function rowHtml(cls, iconCls, title, meta, href) {
    return `<a class="alert-row ${cls}" href="${href}">
      <span class="ar-ic ic-16"><span class="icon ${iconCls}"></span></span>
      <div><strong>${escapeHtml(title)}</strong><div class="ar-meta">${escapeHtml(meta)}</div></div>
      <span class="ar-cta">Ver →</span>
    </a>`;
  }

  function emptyHtml() {
    return `<div class="alert-row ar-info" style="cursor: default">
      <span class="ar-ic ic-16"><span class="icon icon-check"></span></span>
      <div><strong>Nenhum alerta no momento.</strong><div class="ar-meta">Tudo certo por aqui.</div></div>
      <span></span>
    </div>`;
  }

  // ─── Render: contadores de quick actions ────────────────────────────
  function updateQuickActionCounts(alerts) {
    const review = $('#qa-review-count');
    if (review) {
      const n = (alerts.pending_review || []).length;
      review.textContent = n;
      if (!n) review.classList.add('hidden');
    }
    const mineCount = $('#qa-mine-count');
    const mineMeta = $('#qa-mine-meta');
    if (mineCount && alerts.rejected) {
      const n = alerts.rejected.length;
      if (n > 0) {
        mineCount.textContent = n;
        mineCount.classList.remove('hidden');
        if (mineMeta) mineMeta.textContent = `${n} reprovadas precisam de correção`;
      }
    }
  }

  // ─── Render: tabela de notas recentes ───────────────────────────────
  function renderRecent(invoices) {
    const tbody = $('#dashboard-recent tbody');
    if (!tbody) return;
    if (!invoices.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="text-muted" style="text-align:center; padding: 22px">Nenhuma nota recente.</td></tr>`;
      return;
    }
    tbody.innerHTML = invoices.map((inv) => `
      <tr data-href="/invoices/${inv.id}">
        <td style="font-weight: 600">${escapeHtml(inv.invoice_number || '—')}</td>
        <td>${escapeHtml(inv.supplier_name || inv.supplier || '—')}</td>
        <td>${fmtBRL(inv.amount)}</td>
        <td>${fmtDate(inv.due_date)}</td>
        <td>${statusBadgeHtml(inv.status)}</td>
      </tr>
    `).join('');
    // Navegação por linha (mantém padrão das outras tabelas do produto)
    $$('#dashboard-recent tbody tr[data-href]').forEach((tr) => {
      tr.style.cursor = 'pointer';
      tr.addEventListener('click', () => { window.location.href = tr.dataset.href; });
    });
  }

  // ─── Contador "Conferidas hoje" (CONTAS_A_PAGAR) ────────────────────
  async function loadConferredToday() {
    const target = $('#conferidas-hoje-count');
    if (!target) return;
    try {
      const r = await fetch('/api/contas-a-pagar/stats', { credentials: 'same-origin' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      const data = await r.json();
      target.textContent = data.conferred_today != null ? data.conferred_today : '0';
    } catch (err) {
      // Fallback silencioso — se o endpoint ainda não existir, deixa "—"
      // e não polui o console em produção.
      target.textContent = '—';
    }
  }

  // ─── Fetch helpers ──────────────────────────────────────────────────
  async function fetchJson(url) {
    const r = await fetch(url, { credentials: 'same-origin' });
    if (!r.ok) throw new Error('HTTP ' + r.status + ' em ' + url);
    return r.json();
  }

  // ─── Init ───────────────────────────────────────────────────────────
  async function init() {
    setGreeting();
    bindScannerShortcut();

    // Alertas — uma chamada cobre todos os perfis
    try {
      const alerts = await fetchJson('/api/alerts');
      renderAlertsCap(alerts);
      renderAlertsApprover(alerts);
      updateQuickActionCounts(alerts);
    } catch (err) {
      console.warn('Falha ao carregar /api/alerts:', err);
    }

    // Notas recentes
    try {
      const invoices = await fetchJson('/api/invoices?limit=5&order=created_desc');
      renderRecent(Array.isArray(invoices) ? invoices : (invoices.items || []));
    } catch (err) {
      console.warn('Falha ao carregar /api/invoices:', err);
      const tbody = $('#dashboard-recent tbody');
      if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="text-muted" style="text-align:center; padding: 22px">Não foi possível carregar as notas recentes.</td></tr>`;
    }

    // Contador de conferências (só renderiza se o elemento existir)
    loadConferredToday();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
