/* Script da pagina /offline.html — separado do inline pra respeitar a
 * CSP do sistema (script-src 'self' SEM unsafe-inline). Precisa ser
 * pre-cacheado pelo Service Worker pra que execute mesmo quando o
 * usuario abre a pagina sem internet.
 *
 * Responsabilidades:
 *  - Atualiza badge de status conforme rede.
 *  - Recarrega automaticamente quando volta online.
 *  - Polling em /health/live a cada 5s como fallback (caso navigator.onLine
 *    esteja errado, ex: VPN, hotspot capturado, etc.).
 *  - Botao "Tentar de novo" recarrega a pagina.
 */
(function () {
  'use strict';

  function getStatusEl() { return document.getElementById('conn-status'); }
  function getTextEl() { return document.getElementById('conn-text'); }

  function refreshStatus() {
    var status = getStatusEl();
    var text = getTextEl();
    if (!status || !text) return;
    if (navigator.onLine) {
      status.classList.add('online');
      text.textContent = 'Conexao detectada — recarregando...';
      // Pequeno delay pra animacao do badge ser visivel + dar chance
      // do servidor aceitar requests novamente.
      setTimeout(function () { window.location.reload(); }, 800);
    } else {
      status.classList.remove('online');
      text.textContent = 'Aguardando conexao...';
    }
  }

  // Eventos nativos do browser.
  window.addEventListener('online', refreshStatus);
  window.addEventListener('offline', refreshStatus);

  // Botao Tentar de novo.
  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('retry-btn');
    if (btn) {
      btn.addEventListener('click', function () { window.location.reload(); });
    }
    // Roda uma vez na carga pra setar texto inicial.
    refreshStatus();
  });

  // Backup: polling em /health/live a cada 5s. Quando o endpoint
  // responder OK, recarrega — cobre cenarios onde navigator.onLine
  // esta errado (ex: hotspot que conecta wifi mas sem internet).
  setInterval(function () {
    if (!navigator.onLine) return;
    fetch('/health/live', { cache: 'no-store' })
      .then(function (r) { if (r.ok) window.location.reload(); })
      .catch(function () { /* ainda offline — segue esperando */ });
  }, 5000);
})();
