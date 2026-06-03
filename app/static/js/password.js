// Password recovery pages. Loaded after app.js on forgot/reset templates.

function initForgotPasswordPage() {
  document.getElementById('forgot-password-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const email = document.getElementById('forgot-email').value.trim();
    if (!email) return;
    const msgEl = document.getElementById('forgot-message');
    try {
      await fetch('/auth/forgot-password', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email })
      });
      msgEl.textContent = 'Se este email estiver cadastrado, voce recebera um codigo em alguns segundos. Verifique sua caixa de entrada e spam.';
      msgEl.classList.remove('hidden');
      setTimeout(() => { window.location.href = `/reset-password?email=${encodeURIComponent(email)}`; }, 2500);
    } catch (e) {
      showToast('Erro ao processar pedido. Tente novamente.', 'error');
    }
  });
}

function initResetPasswordPage() {
  // Pre-preenche email se veio via querystring
  const params = new URLSearchParams(window.location.search);
  const emailParam = params.get('email');
  if (emailParam) document.getElementById('reset-email').value = emailParam;

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
