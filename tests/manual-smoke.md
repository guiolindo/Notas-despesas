# Smoke test manual — checklist

Lista do que verificar no navegador depois de qualquer mudança no
frontend (split de JS, refactor de CSS, mexer no Auth). Não é
substituto da suite pytest do backend — é complemento.

Roda em ~10 minutos com olho humano. Sem ferramenta automatizada
até instalarmos Playwright/Browser.

## Como rodar

1. Subir o app local:
   ```bash
   uvicorn app.main:app --reload
   ```
2. Abrir o navegador em `http://localhost:8000`
3. Abrir DevTools (F12) → console + network ligados
4. Seguir o checklist abaixo, anotando OK/FALHA por item

Para reset rápido entre tentativas: `Application → Storage → Clear`
no DevTools + recarregar.

## Critérios de aprovação

Cada item tem que cumprir os 3:

1. **Sem erro vermelho no console** (warnings amarelos são OK)
2. **Botão responde ao clique** (não fica morto)
3. **Comportamento esperado acontece** (modal abre, redirect, request, etc)

Se algum item falhar, o split daquele commit não passa. Reverter
ou corrigir antes de continuar.

---

## Páginas públicas (sem login)

### /login

- [ ] Página carrega sem erro console
- [ ] Logo + formulário visíveis
- [ ] Campo email aceita digitação
- [ ] Campo senha aceita digitação
- [ ] Botão "mostrar senha" alterna `type` (text ↔ password)
- [ ] Botão "Entrar" envia formulário (DevTools → Network mostra
      POST /auth/login)
- [ ] Login com credenciais erradas → mensagem de erro vermelha
      aparece embaixo
- [ ] Login com credenciais certas → redirect para /dashboard

### /forgot-password

- [ ] Página carrega sem erro
- [ ] Formulário aceita email
- [ ] Submit dispara POST /auth/forgot-password
- [ ] Mensagem "se este email estiver cadastrado..." aparece
- [ ] Após 2.5s redireciona pra /reset-password?email=...

### /reset-password

- [ ] Página carrega sem erro
- [ ] Email pré-preenchido vindo da querystring
- [ ] Campos email, código e nova senha aceitam digitação
- [ ] Submit dispara POST /auth/reset-password
- [ ] Com código inválido → mensagem de erro
- [ ] Com código válido → toast verde + redirect /login

### /verify/{invoice_id} (público sem login)

- [ ] Página carrega sem erro
- [ ] Nome mascarado aparece (ex: "João S****")
- [ ] CPF/CNPJ mascarado (ex: "***.456.789-**")
- [ ] Sem flash de dados completos

### 404

- [ ] Acessar /nada-aqui → tela 404 amigável
- [ ] Contador 3s funciona
- [ ] Botão "Ir agora" redireciona pra /login (anônimo) ou
      /dashboard (logado)

---

## Páginas autenticadas (após login)

### /change-password (forçado quando must_change_password=True)

- [ ] Página carrega após login do admin default
- [ ] Banner amarelo "É necessário trocar a senha" visível
- [ ] Tentar navegar fora (clicar em link) → bloqueado se forçado
- [ ] Refresh → não pula a tela
- [ ] Submit com senha fraca → erro "deve ter 8 chars com letra e número"
- [ ] Submit com confirmação errada → erro "confirmação não confere"
- [ ] Submit válido → redirect /dashboard

### /dashboard

- [ ] Página carrega
- [ ] Header com nome do usuário + role
- [ ] Sidebar com links de navegação
- [ ] Badge de alertas (se houver) com número
- [ ] Cards/widgets renderizam (admin tem cards diferentes
      de funcionário, etc)

### /invoices (listagem)

- [ ] Tabela carrega com dados
- [ ] Paginação visível e funciona
- [ ] Filtros (status, faixa de data, busca) funcionam
- [ ] Click em uma linha → drawer abre
- [ ] Botão "Nova nota" → vai pra /invoices/create

### /invoices/create

- [ ] Form carrega vazio
- [ ] Lookup de CNPJ funciona (digitar 14 dígitos)
- [ ] Upload de PDF aceita arquivo
- [ ] Botão "Enviar" tenta submit
- [ ] Validação client-side funciona (datas, valores)

### /invoices/{id} (detail)

- [ ] Página carrega com dados da nota
- [ ] Timeline mostra histórico
- [ ] Anexos listados
- [ ] PDF viewer inline carrega o anexo
- [ ] Thread de comentários carrega
- [ ] Comentar funciona (input + botão)
- [ ] Botões de ação (cancelar, etc) clicáveis conforme role

### /admin/users (admin)

- [ ] Lista de usuários carrega
- [ ] Botão "Novo usuário" abre form
- [ ] Editar usuário existente abre form preenchido
- [ ] Encerrar usuário pede confirmação

### /admin/audit-logs

- [ ] Lista de auditoria carrega
- [ ] Filtros funcionam
- [ ] Botão "Verificar cadeia" dispara request e mostra resultado

### /configuracoes

- [ ] Toggle de indisponibilidade visível
- [ ] Botão de logout funciona

### Hamburger menu mobile

- [ ] Em viewport < 1024px o hambúrguer aparece
- [ ] Click no hambúrguer abre/fecha sidebar
- [ ] Click no backdrop fecha

### Atalhos de teclado

- [ ] Tecla `?` abre cheatsheet
- [ ] `Esc` fecha modal/drawer
- [ ] `g d` navega para dashboard
- [ ] `g i` navega para invoices

---

## Smoke após reload

- [ ] F5 em qualquer página autenticada → continua logado
      (não cai pra /login)
- [ ] Hard reload (Ctrl+F5) → idem
- [ ] Abrir nova aba → sessão continua
- [ ] Fechar aba e reabrir → sessão continua (cookie ainda válido)

---

## Smoke após logout

- [ ] Click em "Sair" → redirect /login
- [ ] Voltar com botão do browser → cookie limpo, força /login
- [ ] localStorage limpo (DevTools → Application → Local Storage)

---

## O que NÃO precisa testar manualmente

Coberto pela suite pytest (`python -m pytest tests/ -q`):

- `/health/live`, `/health/ready`, `/health/dependencies`
- Rate-limit em /auth/login e /auth/forgot-password
- 428 quando must_change_password=True
- 404 indistinguível em /verify-full
- Refresh token apagando cookie em falha
- Manager unavailable substituindo
- Duplicate detection
- Email queue (PENDING → SENT/FAILED)

---

## Registro

Quando rodar este checklist, criar comentário no commit ou PR com:

```
Smoke runtime — <data>
Browser: <Chrome X / Edge Y>
Resultado: <todos OK / falhou em X, Y>
Observação: <delay perceptível em X, console limpo, etc>
```
