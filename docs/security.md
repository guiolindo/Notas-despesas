# Segurança — como autenticação e proteção funcionam

Este documento explica os mecanismos de segurança do sistema:
autenticação, sessão, criptografia, rate-limit, defesa contra
abuso. Inclui o "por quê" das decisões — não só o "como".

## Autenticação — visão geral

O fluxo de login segue o padrão **JWT com refresh token em cookie
HttpOnly**:

```
1. Usuário envia email + senha em POST /auth/login
2. Servidor valida com bcrypt (12 rounds, salt único)
3. Servidor responde com:
   • access_token (vida curta: 60 minutos)
   • refresh_token (vida longa: 7 dias) num cookie HttpOnly,
     SameSite=Strict, Secure=true em PROD
4. Cliente guarda access_token em MEMÓRIA (closure JavaScript)
5. Cada request à API leva o access_token no header Authorization
6. Quando o access_token expira, o cliente chama /auth/refresh
   automaticamente (o cookie HttpOnly vai junto) e recebe novo
   access_token sem o usuário perceber
```

### Por que access em memória e não em localStorage?

Antes, o access_token vivia no `localStorage`. Qualquer XSS bem
sucedido podia ler `localStorage.access_token` e exfiltrar via
fetch externo, assumindo a sessão por até 1 hora.

Agora o token vive em uma variável dentro de uma closure JavaScript
(no Auth helper em `app/static/js/app.js`). Não é acessível via
`window`, `localStorage`, nem `sessionStorage`. Um XSS ainda pode
fazer requests usando o token enquanto a aba está aberta, mas:

- Não consegue **exfiltrar** o token bruto para um servidor externo
- Reload da página apaga o token (memória zera)
- Múltiplas abas independentes têm tokens próprios

O cookie HttpOnly de refresh é inacessível pelo JavaScript (até
mesmo o JS legítimo do próprio site). Combinado com SameSite=Strict,
ele só vai junto em requests do mesmo domínio.

### Por que isso não atrapalha F5/reload?

Quando o usuário recarrega a página:

1. Memória do JavaScript zera → `_accessToken = null`
2. O cookie HttpOnly de refresh ainda existe no navegador
3. O Auth helper detecta que tem `sessionStorage.auth_has_session=1`
   (uma flag binária sem segredo, marcada no último login)
4. Dispara automaticamente `POST /auth/refresh` em segundo plano,
   antes mesmo do DOMContentLoaded
5. Servidor valida o cookie, devolve novo access_token
6. Auth helper guarda em memória
7. UI sobe normalmente, sem o usuário ver "tela de login" no meio

O sinal `sessionStorage.auth_has_session` é apenas um booleano —
não contém o token nem dados sensíveis. Serve para o cliente
saber "já estive logado nesta aba" e antecipar o `/refresh`.

---

## Invalidação de sessão após troca/reset de senha

Cenário clássico de vulnerabilidade: atacante captura cookie de
refresh de outra pessoa. Vítima descobre e troca a senha. Em
sistemas mal projetados, o atacante continua renovando access
tokens normalmente por dias.

O Economart resolve isso com a coluna `User.password_changed_at`
e o helper `token_is_pre_password_change` em
`app/security/dependencies.py`:

- Cada vez que o usuário troca senha (`/auth/change-password`) ou
  reset por código (`/auth/reset-password`), `password_changed_at`
  é atualizado para o instante atual
- Cada JWT (access **e** refresh) carrega `iat` (issued-at, padrão JWT)
- Em **três** pontos do código validamos `iat < password_changed_at`:
  1. `get_current_user` (cada request autenticada)
  2. `/auth/refresh` (cada renovação)
  3. `_get_user_from_cookie` (cada page guard)
- Se `iat` é anterior a `password_changed_at`, o token é rejeitado
  com HTTP 401 e o cookie de refresh é apagado

Detalhe sutil: o `iat` do JWT é gravado em **segundos inteiros**, mas
`password_changed_at` no banco tem precisão de **microsegundo**.
Sem cuidado, login imediatamente após troca de senha tem
`iat=1717445092` ≈ `password_changed_at=2026-06-03T20:21:32.500`
e o `iat` truncado fica meio segundo "antes". Resolvemos com
**tolerância de 2 segundos** no helper — comportamento seguro porque
em produção a janela típica entre troca e novo login é de minutos,
não milissegundos.

---

## Hash de senhas

Senhas são guardadas com **bcrypt**:

- Cost factor 12 (~250ms por hash em hardware moderno)
- Salt único por senha (gerado automaticamente pelo bcrypt)
- Verificação em tempo constante (resistência a timing attacks)

**Política de senha** (em `validate_password` no frontend e em
`app/routers/auth.py:change_password` no backend):

- Mínimo 8 caracteres
- Pelo menos uma letra
- Pelo menos um número

Decisão deliberadamente conservadora: regras complexas
("um símbolo, uma maiúscula, etc") aumentam atrito sem aumentar
significativamente a entropia em comparação com tamanho. Para
maior segurança o caminho é **aumentar o tamanho mínimo**, não
adicionar regras.

---

## Bloqueio por tentativas falhas

- 5 senhas erradas em sequência → conta bloqueada por **10 minutos**
- Bloqueio é registrado em `User.blocked_until`
- Tentativas de login durante bloqueio retornam HTTP 403 com mensagem
- Email automático notifica o titular da conta sobre o bloqueio
  (para que ele saiba que alguém está tentando entrar)
- Após o tempo de bloqueio, a conta volta automaticamente
- Login bem-sucedido zera o contador

---

## Must change password

Usuários criados pelo admin nascem com flag `must_change_password=True`.
Enquanto a flag está True:

- Frontend redireciona para `/change-password` automaticamente
- Backend devolve **HTTP 428 Precondition Required** em qualquer
  rota fora da whitelist (apenas `/auth/me`,
  `/auth/change-password` e `/auth/logout` passam)
- `apiFetch` no JavaScript intercepta o 428 e redireciona

A combinação garante que cliente direto via curl ou integração
customizada não consegue contornar a obrigação alterando só o
frontend.

---

## Criptografia de PDFs

PDFs anexados às notas são criptografados antes de subir para o R2:

```
PDF original (em memória)
       │
       ▼
Gera chave Fernet única para este arquivo
       │
       ├──► Criptografa o PDF com a chave (AES-128-CBC + HMAC-SHA256)
       │              │
       │              ▼
       │       Sobe .enc para o R2
       │
       └──► Criptografa a chave Fernet com MASTER_ENCRYPTION_KEY
                      │
                      ▼
              Salva no banco como invoice_attachments.encryption_key_enc
```

Vantagens:

- Cada arquivo tem chave própria (compromisso de um arquivo não
  expõe os outros)
- Banco guarda só a chave criptografada, nunca a chave bruta
- R2 guarda o conteúdo criptografado — vazamento de bucket não
  expõe os PDFs em claro
- `MASTER_ENCRYPTION_KEY` fica apenas em variável de ambiente
  (Railway secrets), não no banco e não no código

Para descriptografar:

1. Lê `encryption_key_enc` do banco
2. Decripta com `MASTER_ENCRYPTION_KEY` para obter a chave Fernet
3. Baixa o `.enc` do R2
4. Decripta o conteúdo com a chave Fernet
5. Devolve o PDF original para o usuário

Tudo isso roda em memória — o PDF em claro nunca toca o disco
do servidor.

---

## Verify público e máscara LGPD

A página `/verify/{invoice_id}` é **pública** (acessível sem login)
mas mostra dados mascarados:

- Nomes: `Maria S****` em vez de `Maria Silva Santos`
- Emails: `mariasilva@economart...` em vez de email completo
- CPF/CNPJ: `***.456.789-**` em vez de número completo

O backend nunca envia os dados não mascarados na renderização
inicial da página. JavaScript do cliente detecta se tem sessão
ativa via `window.Auth.hasSessionHint()`. Se tem, chama
`/api/invoices/{id}/verify-full` (endpoint autenticado) e
reescreve a página com os dados completos.

Isso significa que mesmo que um link da página seja
compartilhado externamente (cliente, auditor, etc), nada sensível
vaza. Quem é da empresa e clica no link, vê tudo após login.

---

## Rate-limit

Cinco endpoints têm rate-limit aplicado via
`app/middleware/security.py:RateLimitMiddleware`:

| Endpoint | Método | Limite | Janela | Por que |
|---|---|---|---|---|
| `/auth/login` | POST | 10 | 60s | Brute force |
| `/auth/forgot-password` | POST | 5 | 600s | Spam de códigos |
| `/auth/reset-password` | POST | 8 | 600s | Brute force do código |
| `/api/invoices/lookup-cnpj/*` | GET | 30 | 60s | Custo da API externa |
| `/api/invoices/*/comments` | * | 30 | 60s | Flood na UI |

O bucket é por (regra, cliente). O cliente é identificado por:

- **Token JWT** se presente (sub do token) — evita que um NAT
  corporativo trave 10 funcionários por um único IP
- **IP** caso contrário

Em produção atrás de proxy (Railway), o middleware honra
`X-Forwarded-For` para obter o IP real do cliente — apenas em
PROD, para que tráfego direto em DEV não possa spoofar o header.

Quando o limite é atingido, resposta é HTTP 429 com cabeçalhos:

- `Retry-After: <segundos>`
- `X-RateLimit-Limit: <limite>`
- `X-RateLimit-Window: <segundos da janela>`

Limitação conhecida: bucket é em memória, por processo. Multi-worker
do gunicorn tem N buckets independentes. Suficiente para a escala
atual; quando crescer, migrar para Redis está documentado como
roadmap.

---

## CSRF

Não usamos tokens CSRF tradicionais. A defesa contra CSRF vem de
três camadas:

1. **Bearer token no header**: a maior parte das mutações é via
   `Authorization: Bearer <token>`. Browsers não anexam headers
   customizados automaticamente em requests cross-origin de
   formulários — só JavaScript do mesmo domínio consegue
2. **Cookie SameSite=Strict**: o cookie de refresh só vai junto
   em requests originadas do próprio domínio
3. **CSP estrita**: `script-src 'self'` sem `unsafe-inline` impede
   que script externo execute no contexto do site

Combinados, esses três cobrem CSRF para o modelo de uso atual.

---

## Content Security Policy (CSP)

Headers configurados em `SecurityHeadersMiddleware`:

```
default-src 'self'
style-src 'self' 'unsafe-inline' https://fonts.googleapis.com
font-src https://fonts.gstatic.com
img-src 'self' data:
script-src 'self' https://cdn.jsdelivr.net
frame-src 'self' blob:
object-src 'none'
base-uri 'self'
```

Pontos importantes:

- **`script-src` sem `unsafe-inline`**: nenhum `<script>` inline
  no HTML executa. Todo JavaScript vem de arquivo externo (cobre
  XSS injetado via formulário)
- **`style-src` com `unsafe-inline`**: necessário porque vários
  templates usam `style="..."` para espaçamento contextual.
  Risco baixo
- **jsdelivr liberado**: apenas para o `jsQR` usado no scanner
- **`object-src 'none'`**: bloqueia `<object>`, `<embed>`,
  `<applet>` (vetores históricos de XSS)
- **`frame-src 'self' blob:`**: permite incorporar PDFs gerados
  como blob (viewer interno) sem expor o site a clickjacking
  externo

Outros headers de segurança setados:

- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Permissions-Policy: camera=(self), microphone=(), geolocation=()`

---

## Fail-fast em PROD para secrets inseguras

Se o app sobe em PROD com:

- `SECRET_KEY` no valor padrão inseguro (ou string com menos de 32 chars)
- ou `MASTER_ENCRYPTION_KEY` vazia

`startup_security_failure()` em `app/config.py` detecta. O middleware
em `app/main.py` então **intercepta todas as requests** e responde
HTTP 503 com a tela amigável `templates/startup_error.html`.

Exceções:

- `/health/live` continua respondendo OK (orquestrador precisa saber
  que o processo subiu)
- `/static/*` continua servindo (a própria tela usa CSS estático)

DEV não bloqueia — apenas mostra warning no log. Permite
desenvolvimento local sem perder tempo gerando chaves.

Decisão de design: **bloquear o deploy é mais seguro do que subir
com config degradada**. Operador percebe imediatamente que algo
está errado e corrige antes de qualquer dado real ser
processado.

---

## Defesa contra admin malicioso

Três mecanismos coordenados (já mencionados em [domain-model.md](domain-model.md)):

### 1. SMTP só via env

A tabela `smtp_settings` no banco ainda existe por compatibilidade
histórica mas o backend **não usa**. O serviço de email
(`app/services/email_service.py`) lê apenas variáveis de ambiente
(`SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, ou `RESEND_API_KEY`).

Um admin malicioso que consegue acesso à UI do sistema não consegue
trocar o provedor de email — apenas quem opera o orquestrador
(Railway, EC2, etc) pode mexer nas variáveis. Isso impede um
ataque clássico: admin malicioso troca o SMTP para servidor próprio,
solicita reset de senha de outro admin/diretor, intercepta o
código no servidor falso.

### 2. Janela de 24h para ações administrativas sensíveis

Em `app/models/pending_admin_actions.py`. Quando o admin:

- Cria outro admin
- Cria um diretor
- Encerra (anonimiza) uma conta

A ação **não acontece imediatamente**. É registrada em
`pending_admin_actions` com status `PENDING_GRACE`. Durante 24h,
outro admin ou diretor pode vetar via interface (POST
`/api/pending-actions/{id}/veto`).

Se ninguém objetar em 24h, um job de background promove a ação
automaticamente para `EXECUTED`. Se alguém vetar, o status vai
para `VETOED` e a ação nunca acontece.

Cada notificação por email para outros admins/diretores no momento
do registro alerta para a janela de revisão.

### 3. Hash chain do audit_log

Em `app/models/audit_logs.py:attach_audit_chain_listener`.

Antes de cada insert em `audit_logs`, o listener:

1. Calcula `prev_hash` pegando o `row_hash` do último registro
2. Calcula `row_hash` deste registro como
   `SHA256(prev_hash + user_id + action + resource_id + timestamp + ip)`
3. Grava ambos

Cada `row_hash` depende do `prev_hash`. Modificar/deletar qualquer
registro retroativo quebra a cadeia em todos os registros posteriores.

Endpoint admin `/api/admin/audit-logs/verify-chain` valida a cadeia
inteira: recalcula cada `row_hash` e compara. Diferença em qualquer
ponto sinaliza tampering.

Mesmo um admin com acesso direto ao Postgres não consegue
"limpar registros incômodos" sem essa verificação detectar.

---

## LGPD checklist

Mecanismos implementados que atendem a LGPD:

- ✅ **Minimização**: JWT tem só `sub` e `role`. Tokens não trafegam
  nome, email, CPF.
- ✅ **Pseudonimização**: IPs em audit_log via HMAC-SHA256 com
  segredo do servidor. Admin não reverte o hash em IP, mas consegue
  ver se duas ações vieram do mesmo IP (necessário para
  correlação de incidentes — Marco Civil Art. 15)
- ✅ **Direito de exclusão**: admin pode "encerrar" usuário, o que
  substitui nome/email por valores neutros (`Colaborador Desligado`,
  `purged-{uuid}@desligado.local`). Audit logs e histórico
  preservados estruturalmente
- ✅ **Retenção**: notas reprovadas auto-delete em 90 dias
  (`purge_old_rejected_invoices` em `app/main.py`). Notas pagas
  ficam (CTN exige mínimo 5 anos para fins fiscais)
- ✅ **Verify público mascarado**: dados sensíveis só aparecem para
  quem tem login válido na empresa
- ✅ **Página de privacidade**: `/privacidade` documenta tudo para
  usuários finais
- ✅ **Códigos de reset com TTL**: códigos de 6 dígitos expiram em
  10 minutos
- ✅ **Audit log de eventos sensíveis**: login, logout, reset de
  senha, troca de senha, criação/encerramento de usuário, todas
  as transições de nota.

---

## O que ainda falta (roadmap de segurança)

- Audit log de **leituras** sensíveis (quem viu CPF X em Y data)
- Backup off-site automatizado do Postgres
- Versioning no R2 (proteção contra delete acidental)
- Sentry/Loki para correlação centralizada de logs
- Cobertura de testes de segurança automatizados (já temos suite
  pytest cobrindo P0/P1, mas dá pra crescer)

---

## Onde isso vive no código

| Conceito | Arquivos |
|---|---|
| Login + bloqueio | `app/routers/auth.py` |
| JWT (gerar/decodificar) | `app/security/jwt.py` |
| Bcrypt | `app/security/hashing.py` |
| Dependencies de auth | `app/security/dependencies.py` |
| Page guard (cookie) | `app/security/page_auth.py` |
| Pseudonimização de IP | `app/security/hashing.py:pseudonymize_ip` |
| Middleware headers + rate-limit | `app/middleware/security.py` |
| Middleware request_id | `app/middleware/observability.py` |
| Criptografia de PDF | `app/services/drive_service.py` |
| Hash chain audit | `app/models/audit_logs.py` |
| Pending admin actions | `app/models/pending_admin_actions.py` + `app/routers/pending_actions.py` |
| Fail-fast PROD | `app/config.py` + `app/main.py` |
| Tela 503 | `app/templates/startup_error.html` |
