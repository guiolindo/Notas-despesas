/* Modulo de recuperacao e troca de senha.
 *
 * Carregado DEPOIS de app.js — depende de window.Auth, window.apiFetch,
 * window.showToast e window.validatePassword expostos por app.js.
 *
 * Exposicao via namespace window.Economart.password.* para evitar
 * poluicao do global. Dispatcher principal continua no app.js — este
 * arquivo NAO registra DOMContentLoaded proprio.
 *
 * Refator do P2-1 v2 (auditoria). Versao anterior (commit c6e67aa) foi
 * revertida por suposta regressao de race condition. Esta versao mantem
 * o dispatcher centralizado em app.js e nao mexe em Auth ou pre-warm —
 * apenas hospeda os handlers de pagina das 3 telas de senha. */
(function () {
  'use strict';

  // Garante namespace mesmo se algum dia este arquivo for carregado antes
  // do app.js (defesivo — nao deveria acontecer no fluxo normal).
  window.Economart = window.Economart || {};
  window.Economart.password = window.Economart.password || {};

  function getAuth() {
    if (!window.Auth) {
      console.error('[password] window.Auth indisponivel — app.js nao carregou?');
      return null;
    }
    return window.Auth;
  }

  function getApiFetch() {
    if (!window.apiFetch) {
      console.error('[password] window.apiFetch indisponivel — app.js nao carregou?');
      return null;
    }
    return window.apiFetch;
  }

  function getShowToast() {
    return window.showToast || function (msg) { console.log('[toast]', msg); };
  }

  function getValidatePassword() {
    return window.validatePassword || function (pwd) {
      // Fallback minimo se o validador global nao estiver disponivel.
      return typeof pwd === 'string' && pwd.length >= 8
        && /[A-Za-z]/.test(pwd) && /[0-9]/.test(pwd);
    };
  }

  /** Pagina /change-password. Usuario logado troca a propria senha.
   *  Quando must_change_password=true, bloqueia navegacao ate trocar. */
  function initChange() {
    const Auth = getAuth();
    if (!Auth) return;
    const apiFetch = getApiFetch();
    if (!apiFetch) return;
    const validatePassword = getValidatePassword();

    if (!Auth.getToken()) {
      window.location.href = '/login';
      return;
    }
    const user = Auth.getUser();
    const isForced = Boolean(user && user.must_change_password);
    if (isForced) {
      document.getElementById('force-change-banner')?.classList.remove('hidden');
    }
    let changed = false;
    // So bloqueia navegacao se a troca foi FORCADA (admin resetou ou e
    // primeiro login). Troca voluntaria deve permitir cancelar.
    if (isForced) {
      document.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', (event) => {
          if (!changed) event.preventDefault();
        });
      });
    }
    window.addEventListener('beforeunload', (event) => {
      if (!changed && isForced) {
        event.preventDefault();
        event.returnValue = '';
      }
    });
    document.getElementById('change-password-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const errorEl = document.getElementById('change-password-error');
      const currentPassword = document.getElementById('current-password').value;
      const newPassword = document.getElementById('new-password').value;
      const confirmPassword = document.getElementById('confirm-password').value;
      errorEl.classList.add('hidden');
      if (!validatePassword(newPassword)) {
        errorEl.textContent = 'A nova senha deve ter minimo 8 caracteres, com letra e numero.';
        errorEl.classList.remove('hidden');
        return;
      }
      if (newPassword !== confirmPassword) {
        errorEl.textContent = 'A confirmacao nao confere.';
        errorEl.classList.remove('hidden');
        return;
      }
      try {
        await apiFetch('/auth/change-password', {
          method: 'POST',
          body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
        });
        const u = Auth.getUser();
        if (u) {
          u.must_change_password = false;
          Auth.setUser(u);
        }
        changed = true;
        window.location.href = '/dashboard';
      } catch (error) {
        errorEl.textContent = error.message;
        errorEl.classList.remove('hidden');
      }
    });
  }

  /** Pagina /forgot-password. Anonimo solicita codigo por email. */
  function initForgot() {
    const showToast = getShowToast();
    document.getElementById('forgot-password-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const email = document.getElementById('forgot-email').value.trim();
      if (!email) return;
      const msgEl = document.getElementById('forgot-message');
      try {
        // Nao usa apiFetch — endpoint e publico e nao requer Bearer.
        await fetch('/auth/forgot-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email })
        });
        msgEl.textContent = 'Se este email estiver cadastrado, voce recebera um codigo em alguns segundos. Verifique sua caixa de entrada e spam.';
        msgEl.classList.remove('hidden');
        setTimeout(() => {
          window.location.href = `/reset-password?email=${encodeURIComponent(email)}`;
        }, 2500);
      } catch (e) {
        showToast('Erro ao processar pedido. Tente novamente.', 'error');
      }
    });
  }

  /** Pagina /reset-password. Anonimo redefine senha com codigo. */
  function initReset() {
    const showToast = getShowToast();
    // Pre-preenche email se veio via querystring.
    const params = new URLSearchParams(window.location.search);
    const emailParam = params.get('email');
    if (emailParam) {
      const emailInput = document.getElementById('reset-email');
      if (emailInput) emailInput.value = emailParam;
    }
    document.getElementById('reset-password-form')?.addEventListener('submit', async (event) => {
      event.preventDefault();
      const errorEl = document.getElementById('reset-error');
      errorEl.classList.add('hidden');
      const payload = {
        email: document.getElementById('reset-email').value.trim(),
        code: document.getElementById('reset-code').value.trim(),
        new_password: document.getElementById('reset-new-password').value
      };
      try {
        const resp = await fetch('/auth/reset-password', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || 'Erro');
        showToast('Senha redefinida! Faca login com a nova senha.', 'success');
        setTimeout(() => { window.location.href = '/login'; }, 1500);
      } catch (e) {
        errorEl.textContent = e.message;
        errorEl.classList.remove('hidden');
      }
    });
  }

  window.Economart.password.initChange = initChange;
  window.Economart.password.initForgot = initForgot;
  window.Economart.password.initReset = initReset;
})();
