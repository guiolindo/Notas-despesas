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

  // P1-1 auditoria: pegamos token do window.Auth (memoria, definido pelo
  // app.js) em vez de localStorage. Quem chega na pagina /verify sem o
  // app.js carregado (link publico, aba isolada) cai como anonimo, o que
  // e o comportamento esperado — a pagina ja serve resumo publico
  // mascarado por padrao.
  var Auth = (typeof window !== 'undefined' && window.Auth) ? window.Auth : null;

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
      if (Auth) Auth.clear();
      window.location.href = '/login?next=/verify/' + encodeURIComponent(INVOICE_ID);
    });
  }

  function obtainToken() {
    if (!Auth) return Promise.resolve(null);
    if (Auth.getToken()) return Promise.resolve(Auth.getToken());
    // hint de sessao (sessionStorage) indica que existe cookie de refresh
    // valido — vale gastar 1 /refresh antes de assumir anonimo.
    if (Auth.hasSessionHint()) return Auth.ensureToken();
    return Promise.resolve(null);
  }

  obtainToken().then(function (token) {
    if (!token) {
      show(banner.pub);
      return;
    }
    show(banner.load);
    return fetch('/api/invoices/' + encodeURIComponent(INVOICE_ID) + '/verify-full', {
      headers: { 'Authorization': 'Bearer ' + token, 'Accept': 'application/json' },
      credentials: 'include'
    })
    .then(function (r) {
      if (r.status === 401) {
        if (Auth) Auth.clear();
        hideAll(); show(banner.pub);
        return null;
      }
      // 404 cobre ambos "nao existe" e "sem permissao" desde P1-6.
      // Mantemos a UI publica nesses casos — sem revelar nada extra.
      if (r.status === 403 || r.status === 404) {
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
  });
})();
