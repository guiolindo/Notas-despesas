/* ============================================================================
   dashboard-v2.js — logica do dashboard refeito.
   Carregado APENAS em /dashboard, DEPOIS de app.js (que expoe helpers globais).

   Responsabilidades:
     1. Hidratar contadores (review queue, minhas notas, conferidas hoje)
     2. Renderizar lista de alertas (consumindo /alerts/)
     3. Popular a tabela de notas recentes (/api/invoices/?per_page=5)
     4. Atalho de teclado F2 -> abrir scanner (perfil CONTAS_A_PAGAR)
     5. Saudacao contextual por horario de Brasilia

   Reusa de app.js: apiFetch, escapeHtml, formatCurrency, formatDate,
   statusBadge, hourInBR. NAO redefine essas funcoes localmente.
   ============================================================================ */
(function () {
  'use strict';

  const $ = (sel, root) => (root || document).querySelector(sel);

  // ─── Saudacao por horario de Brasilia ────────────────────────────────
  function setGreeting() {
    const greetEl = $('#dashboard-greeting');
    if (!greetEl) return;
    const txt = greetEl.textContent.trim();
    const first = txt.replace(/^(Ola|Bom dia|Boa tarde|Boa noite),?\s*/i, '');
    const h = hourInBR();
    const prefix = h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
    greetEl.textContent = `${prefix}, ${first}`;
  }

  // ─── Atalho F2 (CONTAS_A_PAGAR) ─────────────────────────────────────
  function bindScannerShortcut() {
    const link = $('#qa-open-scanner');
    if (!link) return;
    document.addEventListener('keydown', function (e) {
      if (e.key !== 'F2') return;
      const tag = (e.target && e.target.tagName) || '';
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.target && e.target.isContentEditable) return;
      e.preventDefault();
      window.location.href = link.href;
    });
  }

  // ─── Render de alertas — generico ───────────────────────────────────
  // Cada spec descreve UMA linha do dashboard. O renderer abaixo pega o
  // bucket no payload e gera o HTML so se tiver itens.
  function rowHtml(cls, iconCls, title, meta, href) {
    return `<a class="alert-row ${cls}" href="${href}">
      <span class="ar-ic ic-16"><span class="icon ${iconCls}"></span></span>
      <div><strong>${escapeHtml(title)}</strong><div class="ar-meta">${escapeHtml(meta)}</div></div>
      <span class="ar-cta">Ver &rarr;</span>
    </a>`;
  }

  const EMPTY_HTML = `<div class="alert-row ar-info dashboard-alert-empty">
    <span class="ar-ic ic-16"><span class="icon icon-check"></span></span>
    <div><strong>Nenhum alerta no momento.</strong><div class="ar-meta">Tudo certo por aqui.</div></div>
    <span></span>
  </div>`;

  const CAP_SPECS = [
    { bucket: 'overdue',      cls: 'ar-err',  icon: 'icon-circle-alert',
      title: n => `${n} notas vencidas a conferir`,
      meta: 'Bucket overdue', href: '/alerts?bucket=overdue' },
    { bucket: 'due_72h',      cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} notas vencem em ate 72 h`,
      meta: 'Bucket due_72h', href: '/alerts?bucket=due_72h' },
    { bucket: 'old_emission', cls: 'ar-info', icon: 'icon-calendar',
      title: n => `${n} notas com emissao do mes anterior`,
      meta: 'Bucket old_emission · confirme prazo de lancamento',
      href: '/alerts?bucket=old_emission' },
  ];

  const APPROVER_SPECS = [
    { bucket: 'pending_review', cls: 'ar-blue', icon: 'icon-activity',
      title: n => `${n} notas aguardando sua aprovacao`,
      meta: 'Bucket pending_review · ordenadas por submitted_at',
      href: '/manager/queue' },
    { bucket: 'overdue',        cls: 'ar-err',  icon: 'icon-circle-alert',
      title: n => `${n} notas vencidas`,
      meta: 'Bucket overdue', href: '/alerts?bucket=overdue' },
    { bucket: 'due_72h',        cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} notas vencem em ate 72 h`,
      meta: 'Bucket due_72h', href: '/alerts?bucket=due_72h' },
    { bucket: 'rejected',       cls: 'ar-err',  icon: 'icon-x',
      title: n => `${n} das suas notas foram reprovadas`,
      meta: 'Bucket rejected (so para o criador) · corrija e reenvie',
      href: '/invoices?status=REPROVADO_GESTOR' },
  ];

  function renderAlerts(rootSel, alerts, specs) {
    const root = $(rootSel);
    if (!root) return;
    const out = specs
      .map((s) => ({ n: (alerts[s.bucket] || []).length, s }))
      .filter(({ n }) => n > 0)
      .map(({ n, s }) => rowHtml(s.cls, s.icon, s.title(n), s.meta, s.href));
    root.innerHTML = out.length ? out.join('') : EMPTY_HTML;
  }

  // ─── Contadores dos quick actions ───────────────────────────────────
  function updateQuickActionCounts(alerts) {
    const review = $('#qa-review-count');
    if (review) {
      const n = (alerts.pending_review || []).length;
      review.textContent = n;
      if (!n) review.classList.add('hidden');
    }
    const mineCount = $('#qa-mine-count');
    const mineMeta = $('#qa-mine-meta');
    const rejN = (alerts.rejected || []).length;
    if (mineCount && rejN > 0) {
      mineCount.textContent = rejN;
      mineCount.classList.remove('hidden');
      if (mineMeta) mineMeta.textContent = `${rejN} reprovadas precisam de correcao`;
    }
  }

  // ─── Tabela de notas recentes ───────────────────────────────────────
  function renderRecent(invoices) {
    const tbody = $('#dashboard-recent tbody');
    if (!tbody) return;
    if (!invoices.length) {
      tbody.innerHTML = `<tr><td colspan="5" class="dashboard-recent-empty text-muted">Nenhuma nota recente.</td></tr>`;
      return;
    }
    tbody.innerHTML = invoices.map((inv) => `
      <tr data-href="/invoices/${escapeHtml(inv.id)}" class="dashboard-recent-row">
        <td class="cell-strong">${escapeHtml(inv.invoice_number || '—')}</td>
        <td>${escapeHtml(inv.supplier_name || inv.supplier_legal_name || '—')}</td>
        <td>${formatCurrency(inv.amount)}</td>
        <td>${formatDate(inv.due_date)}</td>
        <td>${statusBadge(inv.status)}</td>
      </tr>
    `).join('');
    // Delegacao no tbody (um listener, em vez de um por linha)
  }

  // Delegacao registrada uma unica vez ao iniciar
  function bindRecentTableClicks() {
    const tbody = $('#dashboard-recent tbody');
    if (!tbody || tbody.dataset.boundClicks) return;
    tbody.dataset.boundClicks = '1';
    tbody.addEventListener('click', (ev) => {
      const tr = ev.target.closest('tr[data-href]');
      if (!tr) return;
      window.location.href = tr.dataset.href;
    });
  }

  // ─── Conferidas hoje (CONTAS_A_PAGAR) ───────────────────────────────
  async function loadConferredToday() {
    const target = $('#conferidas-hoje-count');
    if (!target) return;
    try {
      const data = await apiFetch('/api/contas-a-pagar/stats');
      target.textContent = data.conferred_today != null ? data.conferred_today : '0';
    } catch (_err) {
      target.textContent = '—';  // fallback silencioso
    }
  }

  // ─── Hidratacao dos paineis principais ──────────────────────────────
  function hydrateAlerts(alerts) {
    renderAlerts('#dashboard-alerts-cap',      alerts, CAP_SPECS);
    renderAlerts('#dashboard-alerts-approver', alerts, APPROVER_SPECS);
    updateQuickActionCounts(alerts);
  }

  function showRecentLoadError() {
    const tbody = $('#dashboard-recent tbody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" class="dashboard-recent-empty text-muted">Nao foi possivel carregar as notas recentes.</td></tr>`;
    }
  }

  // ─── Init ───────────────────────────────────────────────────────────
  async function init() {
    setGreeting();
    bindScannerShortcut();
    bindRecentTableClicks();

    // Paineis principais: dispara em paralelo, trata individualmente.
    // /api/contas-a-pagar/stats so faz sentido pra CONTAS_A_PAGAR — a
    // funcao ja faz no-op se o badge nao existir.
    const [alertsR, invoicesR] = await Promise.allSettled([
      apiFetch('/alerts/'),
      apiFetch('/api/invoices/?per_page=5'),
    ]);

    if (alertsR.status === 'fulfilled') {
      hydrateAlerts(alertsR.value || {});
    } else {
      console.warn('Falha ao carregar /alerts/:', alertsR.reason);
    }

    if (invoicesR.status === 'fulfilled') {
      const payload = invoicesR.value;
      const items = Array.isArray(payload) ? payload : (payload?.items || []);
      renderRecent(items);
    } else {
      console.warn('Falha ao carregar /api/invoices/:', invoicesR.reason);
      showRecentLoadError();
    }

    loadConferredToday();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
