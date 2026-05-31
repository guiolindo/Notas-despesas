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
      title: n => `${n} ${n === 1 ? 'nota vencida' : 'notas vencidas'} a conferir`,
      meta: 'Verifique se ja foi paga ou repasse ao financeiro.',
      href: '/alerts?bucket=overdue' },
    { bucket: 'due_72h',      cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} ${n === 1 ? 'nota vence' : 'notas vencem'} em ate 72 horas`,
      meta: 'Confira a prioridade antes do prazo.',
      href: '/alerts?bucket=due_72h' },
    { bucket: 'old_emission', cls: 'ar-info', icon: 'icon-calendar',
      title: n => `${n} ${n === 1 ? 'nota com emissao' : 'notas com emissao'} do mes anterior`,
      meta: 'Atencao ao prazo de lancamento.',
      href: '/alerts?bucket=old_emission' },
  ];

  const APPROVER_SPECS = [
    { bucket: 'pending_review', cls: 'ar-blue', icon: 'icon-activity',
      title: n => `${n} ${n === 1 ? 'nota aguardando' : 'notas aguardando'} sua aprovacao`,
      meta: 'Ordem de chegada — as mais antigas aparecem primeiro.',
      href: '/manager/queue' },
    { bucket: 'overdue',        cls: 'ar-err',  icon: 'icon-circle-alert',
      title: n => `${n} ${n === 1 ? 'nota vencida' : 'notas vencidas'}`,
      meta: 'Vencimento ja passou.',
      href: '/alerts?bucket=overdue' },
    { bucket: 'due_72h',        cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} ${n === 1 ? 'nota vence' : 'notas vencem'} em ate 72 horas`,
      meta: 'Priorize antes do prazo.',
      href: '/alerts?bucket=due_72h' },
    { bucket: 'rejected',       cls: 'ar-err',  icon: 'icon-x',
      title: n => `${n} ${n === 1 ? 'nota foi reprovada' : 'das suas notas foram reprovadas'}`,
      meta: 'Corrija o que foi apontado e reenvie.',
      href: '/invoices?status=REPROVADO_GESTOR' },
  ];

  // ADMIN ve o sistema todo — sem 'pending_review' (nao aprova) e sem
  // 'rejected' (nao cria); so o que importa pra acompanhar o operacional.
  const ADMIN_SPECS = [
    { bucket: 'overdue',      cls: 'ar-err',  icon: 'icon-circle-alert',
      title: n => `${n} ${n === 1 ? 'nota vencida' : 'notas vencidas'} no sistema`,
      meta: 'Considere alertar os responsaveis.',
      href: '/alerts?bucket=overdue' },
    { bucket: 'due_72h',      cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} ${n === 1 ? 'nota vence' : 'notas vencem'} em ate 72 horas`,
      meta: 'Visao operacional do sistema.',
      href: '/alerts?bucket=due_72h' },
    { bucket: 'old_emission', cls: 'ar-info', icon: 'icon-calendar',
      title: n => `${n} ${n === 1 ? 'nota com emissao' : 'notas com emissao'} antiga`,
      meta: 'Pode indicar atraso no lancamento.',
      href: '/alerts?bucket=old_emission' },
  ];

  // EMPLOYEE so cria notas — alertas relevantes sao as proprias reprovadas
  // (precisam de correcao) e vencimentos curtos nas suas notas em fluxo.
  const EMPLOYEE_SPECS = [
    { bucket: 'rejected', cls: 'ar-err',  icon: 'icon-x',
      title: n => `${n} ${n === 1 ? 'nota sua foi reprovada' : 'notas suas foram reprovadas'}`,
      meta: 'Corrija o que foi apontado e reenvie.',
      href: '/invoices?status=REPROVADO_GESTOR' },
    { bucket: 'due_72h',  cls: 'ar-warn', icon: 'icon-clock',
      title: n => `${n} ${n === 1 ? 'das suas notas vence' : 'das suas notas vencem'} em ate 72 horas`,
      meta: 'Cobre aprovacao se ainda estiverem pendentes.',
      href: '/invoices?created_by=me' },
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
  // Cada perfil tem seu proprio root no template; renderAlerts faz no-op
  // se o seletor nao encontrar nada, entao so um dos quatro entra em jogo.
  function hydrateAlerts(alerts) {
    renderAlerts('#dashboard-alerts-cap',      alerts, CAP_SPECS);
    renderAlerts('#dashboard-alerts-admin',    alerts, ADMIN_SPECS);
    renderAlerts('#dashboard-alerts-employee', alerts, EMPLOYEE_SPECS);
    renderAlerts('#dashboard-alerts-approver', alerts, APPROVER_SPECS);
    updateQuickActionCounts(alerts);
  }

  function showRecentLoadError() {
    const tbody = $('#dashboard-recent tbody');
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="5" class="dashboard-recent-empty text-muted">Nao foi possivel carregar as notas recentes.</td></tr>`;
    }
  }

  // ─── Banner de acoes administrativas pendentes ──────────────────────
  // Mostra acoes que afetam o usuario (target) E acoes que ele pode revisar
  // como peer (diretor / admin). Cada item ganha botoes 'Cancelar' e/ou
  // 'Confirmar' conforme a permissao.
  async function loadPendingActions() {
    const banner = $('#pending-actions-banner');
    if (!banner) return;
    try {
      // /visible inclui acoes contra mim E acoes que posso revisar (peer)
      let items = [];
      try {
        items = await apiFetch('/api/pending-actions/visible');
      } catch {
        // perfis fora de DIRECTOR/ADMIN -> usa /me como fallback
        items = await apiFetch('/api/pending-actions/me');
      }
      if (!items || !items.length) {
        banner.classList.add('hidden');
        return;
      }
      banner.innerHTML = items.map((pa) => {
        const hours = Math.floor(pa.seconds_remaining / 3600);
        const mins = Math.floor((pa.seconds_remaining % 3600) / 60);
        const left = pa.seconds_remaining > 0
          ? `Tempo restante: <strong>${hours}h ${mins}min</strong>`
          : '<strong>Janela expirada</strong> (sera aplicada na proxima atualizacao).';
        const targetTxt = pa.is_target
          ? 'contra <strong>voce</strong>'
          : `contra <strong>${escapeHtml(pa.target_name || '?')}</strong>`;
        const buttons = [];
        if (pa.can_cancel !== false) {
          const label = pa.is_target ? 'Nao foi autorizada' : 'Cancelar';
          buttons.push(`<button class="btn btn-ghost btn-sm" data-pending-cancel="${escapeHtml(pa.id)}">${label}</button>`);
        }
        if (pa.can_confirm) {
          buttons.push(`<button class="btn btn-primary btn-sm" data-pending-confirm="${escapeHtml(pa.id)}">Confirmar e aplicar agora</button>`);
        }
        return `<div class="pending-banner-item">
          <div>
            <strong>${escapeHtml(pa.action_label)}</strong> ${targetTxt},
            solicitada por <strong>${escapeHtml(pa.requested_by_name || '?')}</strong>.
            <div class="pending-banner-sub">${left}</div>
          </div>
          <div class="pending-banner-actions">${buttons.join('')}</div>
        </div>`;
      }).join('');
      banner.classList.remove('hidden');
      banner.querySelectorAll('[data-pending-cancel]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.pendingCancel;
          const reason = window.prompt(
            'Descreva brevemente o motivo do cancelamento (opcional):'
          );
          if (reason === null) return;
          try {
            await apiFetch(`/api/pending-actions/${id}/cancel`, {
              method: 'POST',
              body: JSON.stringify({ reason: reason || null }),
            });
            await loadPendingActions();
          } catch (e) {
            alert(e.message || 'Erro ao cancelar.');
          }
        });
      });
      banner.querySelectorAll('[data-pending-confirm]').forEach((btn) => {
        btn.addEventListener('click', async () => {
          const id = btn.dataset.pendingConfirm;
          if (!window.confirm('Confirmar esta acao agora? O efeito sera aplicado imediatamente, sem esperar as 24h.')) return;
          try {
            await apiFetch(`/api/pending-actions/${id}/confirm`, { method: 'POST' });
            await loadPendingActions();
          } catch (e) {
            alert(e.message || 'Erro ao confirmar.');
          }
        });
      });
    } catch (err) {
      banner.classList.add('hidden');
    }
  }

  // ─── Init ───────────────────────────────────────────────────────────
  async function init() {
    setGreeting();
    bindScannerShortcut();
    bindRecentTableClicks();
    loadPendingActions();

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
