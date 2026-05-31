// Pagina 404: detecta sessao e redireciona pra /dashboard (logado) ou
// /login (anonimo) apos 3s. Botao "Ir agora" apressa a transicao.
(function () {
  'use strict';

  function hasSession() {
    try {
      return Boolean(localStorage.getItem('access_token'));
    } catch (e) {
      return false;
    }
  }

  var target = hasSession() ? '/dashboard' : '/login';
  var btn = document.getElementById('nf-go-now');
  if (btn) btn.setAttribute('href', target);

  var secondsEl = document.getElementById('nf-seconds');
  var remaining = 3;
  var intervalId = window.setInterval(function () {
    remaining -= 1;
    if (secondsEl) secondsEl.textContent = String(Math.max(remaining, 0));
    if (remaining <= 0) {
      window.clearInterval(intervalId);
      window.location.replace(target);
    }
  }, 1000);

  // Se o usuario clicar no botao, cancela o timer pra nao ter race
  if (btn) {
    btn.addEventListener('click', function () {
      window.clearInterval(intervalId);
    });
  }
})();
