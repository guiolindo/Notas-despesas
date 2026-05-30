// Logica da pagina /verify/<id>. Carregado como script externo para
// respeitar a CSP do sistema (script-src sem unsafe-inline).
//
// Estados:
// - sem token: mostra banner publico (resumo + CTA "Entrar")
// - com token + 200: revela dados completos + atalho "Abrir nota"
// - com token + 403: mostra aviso suave + opcao "Trocar de conta"
// - com token + 401: trata como anonimo

(function () {
  var root = document.getElementById('verify-root');
  if (!root) return;
  var INVOICE_ID = root.getAttribute('data-invoice-id');
  if (!INVOICE_ID) return;

  var token = null;
  try { token = localStorage.getItem('access_token'); } catch (e) {}

  var banner = {
    pub: document.getElementById('verify-banner-public'),
    load: document.getElementById('verify-banner-loading'),
    full: document.getElementById('verify-banner-full'),
    denied: document.getElementById('verify-banner-denied'),
  };
  function show(el) { if (el) el.style.display = 'flex'; }
  function hide(el) { if (el) el.style.display = 'none'; }
  function hideAll() { hide(banner.pub); hide(banner.load); hide(banner.full); hide(banner.denied); }

  var switchBtn = document.getElementById('verify-switch-account');
  if (switchBtn) {
    switchBtn.addEventListener('click', function (e) {
      e.preventDefault();
      try {
        localStorage.removeItem('access_token');
        localStorage.removeItem('user');
      } catch (err) {}
      window.location.href = '/login?next=/verify/' + encodeURIComponent(INVOICE_ID);
    });
  }

  // Sem token: visitante / cliente / auditor externo. Mostra resumo publico.
  if (!token) {
    show(banner.pub);
    return;
  }

  // Com token: tenta abrir os dados completos.
  show(banner.load);

  fetch('/api/invoices/' + encodeURIComponent(INVOICE_ID) + '/verify-full', {
    headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' }
  })
    .then(function (r) {
      if (r.status === 401) {
        try { localStorage.removeItem('access_token'); } catch (e) {}
        hideAll(); show(banner.pub);
        return null;
      }
      if (r.status === 403) {
        hideAll(); show(banner.denied);
        return null;
      }
      if (!r.ok) {
        hideAll(); show(banner.pub);
        return null;
      }
      return r.json();
    })
    .then(function (data) {
      if (!data) return;
      hideAll(); show(banner.full);

      function setText(id, value) {
        var el = document.getElementById(id);
        if (el && value != null && value !== '') el.textContent = value;
      }
      setText('vf-supplier-name', data.supplier_legal_name || data.supplier_name);
      setText('vf-supplier-doc', data.supplier_document);
      setText(
        'vf-manager',
        (data.manager_name || '-') + (data.manager_email ? ' · ' + data.manager_email : '')
      );
      setText(
        'vf-director',
        (data.director_name || '-') + (data.director_email ? ' · ' + data.director_email : '')
      );

      document.getElementById('vf-extra').style.display = 'block';
      setText('vf-desc', data.description);
      var dates = [];
      if (data.issue_date) dates.push('Emissao: ' + data.issue_date);
      if (data.due_date) dates.push('Vencimento: ' + data.due_date);
      setText('vf-dates', dates.join(' · '));
      setText('vf-creator', data.created_by_name);
    })
    .catch(function () {
      hideAll(); show(banner.pub);
    });
})();
