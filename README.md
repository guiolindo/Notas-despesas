# Economart — Sistema de Aprovação de Notas Fiscais

Aplicação web completa para gestão do fluxo de notas fiscais de despesa da
Economart Atacadista — desde o lançamento por colaboradores, passando pela
aprovação hierárquica (Gestor → Diretor), até o lançamento final pelo
Financeiro.

[![Deploy on Railway](https://img.shields.io/badge/Deploy-Railway-violet)](https://railway.app)
[![Python](https://img.shields.io/badge/Python-3.12+-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136+-green)](https://fastapi.tiangolo.com/)

---

## Sumário

- [Visão geral](#visão-geral)
- [Stack tecnológica](#stack-tecnológica)
- [Funcionalidades](#funcionalidades)
- [Perfis de usuário](#perfis-de-usuário)
- [Fluxo de aprovação](#fluxo-de-aprovação)
- [Segurança e LGPD](#segurança-e-lgpd)
- [Defesa contra admin malicioso (insider threat)](#defesa-contra-admin-malicioso-insider-threat)
- [Setup local](#setup-local)
- [Deploy no Railway](#deploy-no-railway)
- [Configurações](#configurações)
- [Endpoints HTTP](#endpoints-http)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Convenções de código](#convenções-de-código)
- [Mudanças recentes](#mudanças-recentes)

---

## Visão geral

O sistema digitaliza o fluxo de aprovação de notas fiscais com rastreabilidade
fiscal (Art. 173 CTN) e conformidade LGPD. Cada nota passa por uma máquina de
estados rigorosa (FSM), o PDF original é criptografado com AES (Fernet) e
guardado na Cloudflare R2, e todas as ações geram registros de auditoria
imutáveis com pseudonimização de IPs via HMAC-SHA256.

## Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Backend | FastAPI 0.136+ |
| ORM | SQLAlchemy 2.x |
| Banco | PostgreSQL (Railway) / SQLite (dev local) |
| Templates | Jinja2 (autoescape habilitado) |
| Frontend | HTML5 + CSS3 + JS vanilla (sem framework) |
| Ícones | Lucide vendorizado em `static/img/icons/` (CSS mask, CSP-safe) |
| QR Scanner | jsQR via CDN jsdelivr (liberado na CSP) |
| Storage de PDFs | Cloudflare R2 (S3-compatible, criptografia client-side) |
| Email | SMTP (`smtplib`) ou Resend (HTTP API, recomendado em Railway) |
| Auth | JWT (access 60min) + refresh token HttpOnly (7 dias) |
| Servidor | Gunicorn + Uvicorn workers |
| Deploy | Railway |

## Funcionalidades

### Para colaboradores
- Criar nota fiscal com upload de **até 5 PDFs** (nota + boletos + comprovantes,
  10 MB cada, 25 MB total). Viewer mostra todos os anexos mesclados.
- **CPF/CNPJ do fornecedor obrigatório** com validação Mod 11. CNPJ tem
  autocomplete de razão social via API pública (opencnpj.org, cache de 6 meses).
- Envio direto ao Gestor — ou ao Diretor (se configurado pelo Admin)
- Editar/reenviar notas reprovadas (obrigatório alterar a descrição)
- **Excluir notas reprovadas** que não vai reenviar (sem esperar auto-delete)
- Cancelar notas pendentes (antes de qualquer aprovação)
- Acompanhar status em timeline visual
- **Bloqueio de envio com vencimento já passado** (atualiza a data antes)

### Para gestores
- Fila de notas aguardando aprovação
- Aprovar (encaminha ao diretor) ou Reprovar (com motivo obrigatório de 10+ chars)
- Selecionar diretor responsável ao aprovar
- **Pausar recebimento** durante férias (Configurações → Indisponível)

### Para diretores
- Fila de notas aguardando revisão
- Aprovar (libera para Financeiro) ou Reprovar (com motivo)
- **Criar nota própria** que vai direto ao Financeiro (auto-aprovação)
- **Pausar recebimento** durante férias
- Visualização de notas já lançadas

### Para financeiro
- Fila de notas aprovadas pendentes de lançamento
- Botão único: **Imprimir e Lançar** — comprovante PDF **concatena capa + TODOS os anexos** da nota (QR code + nota + boletos)
- Reimpressão de comprovantes a qualquer momento (sem poluir log)

### Para contas a pagar (perfil `CONTAS_A_PAGAR`)
- **Acesso read-only a todas as notas** — não cria, não aprova, não edita.
- **Página /contas-a-pagar/scanner** com dois modos: bipador (entrada de texto
  com auto-submit) e câmera (jsQR via `getUserMedia`, ideal smartphone).
  Lê QR `/verify/<id>` ou UUID puro.
- **Reimpressão de comprovante** permitida em notas já lançadas (status PAGO).
- Atalho **F2** no dashboard abre o scanner direto.
- Card "Conferidas hoje" — contador de reimpressões nas últimas 24h.

### Para admin
- CRUD completo de usuários (com setor e gestor obrigatórios)
- CRUD de setores com designação de diretores
- Auditoria completa (filtros por ação, usuário, sucesso)
- **Configuração de email automático** — escolha entre SMTP (Gmail, Outlook,
  SendGrid) ou Resend (HTTP API, funciona em Railway sem desbloqueio)
- **Encerrar conta de colaborador desligado** (pseudonimização irreversível —
  nome/email/senha viram placeholders, login permanentemente bloqueado, mas
  histórico de aprovações preservado por 5 anos CTN). Botão só aparece para
  usuário inativo, não-admin, e que ainda não foi encerrado.
- Linha de usuário encerrado tem badge cinza "encerrada" e nenhuma ação de
  edição — o registro permanece para auditoria fiscal mas não pode mais ser
  reativado, editado ou ter senha redefinida.
- **Purge manual de reprovadas** (`/api/admin/maintenance/purge-rejected`)
- Reset de senha de outros usuários (exceto outros admins, anti-sequestro)

### Recursos transversais
- **Busca instantânea** em todas as listagens com filtros combinados
- **Totalizer**: contagem + soma R$ dos resultados filtrados
- **FAQ filtrado por perfil** (rodapé "Perguntas frequentes") — cada papel só
  vê instruções relevantes; admin vê tudo
- **Alertas contextuais na nota**: banner amarelo no detalhe quando emissão é
  do mês anterior/ano anterior, vencimento curto, ou nota reprovada (com motivo)
- **Categoria "Reprovadas (suas)"** no dashboard — só pro criador
- **Auto-delete de reprovadas após 90 dias** (PDFs também removidos do R2)
- **Notificações automáticas por email** em cada transição de estado
- **Recuperação de senha** via código de 6 dígitos enviado por email
- **Alerta de conta bloqueada** após 5 tentativas falhas
- **Verify público** (QR code) com email do aprovador mascarado (LGPD)
- **Página /privacidade** com aviso LGPD completo
- **Configuração SMTP/Resend pelo admin** (sem precisar redeploy)
- **Reenvio de nota reprovada** exige edição da descrição (previne reenvio
  vazio sem mudança real)
- **PDFs com JavaScript embutido bloqueados** no upload (anti-malware leve)
- **Modo férias** — Gestor/Diretor pausam recebimento de notas em
  Configurações; banner amarelo confirma estado indisponível
- **Dashboard adaptado por perfil** — quatro layouts distintos (Admin,
  Employee, Aprovadores, Contas a Pagar) com hero, ações e alertas
  específicos para cada papel
- **Verify público com máscara LGPD** (`/verify/<id>`) — visitantes sem login
  veem nome de fornecedor/gestor mascarado e CPF/CNPJ parcial; quem participa
  do fluxo (criador, gestor, diretor, financeiro, contas a pagar, admin)
  faz login e revela tudo automaticamente, sem flash
- **Página 404 amigável** com contador 3s e redirect inteligente (logado →
  dashboard, anônimo → login). Rotas de API continuam respondendo JSON.
- **Transições suaves entre páginas** via View Transitions API (Chrome 126+),
  fallback CSS para outros browsers, e barra de progresso fina no topo
- **Critical CSS inline** no `<head>` para eliminar flash branco entre navegações
- **Login respeita `?next=`** — usuário clica "Entrar" no /verify e volta
  exatamente pra nota depois do login (validação anti open-redirect)

## Perfis de usuário

| Role | Função |
|---|---|
| `ADMIN` | Gerencia usuários, setores, auditoria e config do sistema. Não aprova notas. |
| `EMPLOYEE` (Funcionário) | Cria notas e acompanha aprovação |
| `MANAGER` (Gestor) | Aprova/reprova notas do seu setor |
| `DIRECTOR` (Diretor) | Aprova/reprova após o gestor. Pode criar nota própria direto pro Financeiro. |
| `FINANCE` (Financeiro) | Lança notas aprovadas e gera comprovantes |
| `CONTAS_A_PAGAR` | Read-only de todas as notas, scanner QR e reimpressão de lançadas |

## Fluxo de aprovação

```
                             ┌─────────────┐
                             │  RASCUNHO   │ ← Funcionário criou
                             └──────┬──────┘
                                    │ envia
                ┌───────────────────┴───────────────────┐
                │ Setor normal                  Atalho │
                ▼                                       ▼
      ┌──────────────────┐                   ┌──────────────────┐
      │ AGUARDANDO_      │                   │ AGUARDANDO_      │
      │ GESTOR           │                   │ DIRETOR          │
      └────────┬─────────┘                   └────────┬─────────┘
        aprova │ reprova                       aprova │ reprova
               │     ↓                                │     ↓
               │  REPROVADO_GESTOR                    │  REPROVADO_DIRETOR
               │                                      │
               └──────────► AGUARDANDO_DIRETOR ◄──────┘
                                    │
                              aprova │
                                    ▼
                            ┌──────────────┐
                            │   APROVADO   │ ← Financeiro vê na fila
                            └──────┬───────┘
                                   │ Imprimir + Lançar
                                   ▼
                            ┌──────────────┐
                            │     PAGO     │ ← finalizada (alias UI: Lançada)
                            └──────────────┘
```

Cada transição gera entrada em `approval_history` + `audit_logs` com:
- ID do usuário responsável
- Timestamp em UTC (exibido em -3 no frontend)
- IP pseudonimizado (HMAC-SHA256, conforme LGPD Art. 46)
- Porta de origem (Marco Civil Art. 15, individualização NAT)
- Comentário (em reprovações)

## Segurança e LGPD

### Autenticação
- Senhas com **bcrypt** (cost factor padrão)
- Validação de complexidade: mínimo 8 chars, letra + número
- **Trocar pela mesma senha é proibido** — `change-password` rejeita 422 se
  a nova bater no hash atual (anti-bypass de `must_change_password=True`)
- JWT access token (60 min) + refresh token HttpOnly cookie (7 dias,
  `SameSite=strict`, `Secure` em PROD)
- Rate limit de login: 5 tentativas → bloqueio 10 min (com email automático ao titular)
- Race condition prevenida com `SELECT FOR UPDATE` no PostgreSQL
- Refresh token revalida usuário no DB a cada uso (rebaixamento/desativação têm efeito imediato)
- **Tokens emitidos antes da última troca de senha são invalidados** — admin
  reseta senha → todas as sessões abertas do usuário caem
- **Logout revoga o access token de verdade** (pentest jun/2026): logout grava
  `session_invalidated_at` no usuário; qualquer access com `iat` anterior cai
  com 401. Antes, só o cookie refresh era apagado e o access continuava
  válido até expirar (~1h), mantendo atacante com token sequestrado na sessão
- **Login e forgot-password com tempo de resposta constante** — bcrypt rodado
  mesmo quando o email não existe + work pesado em BackgroundTasks. Fecha
  enumeração de contas por timing (antes: 350ms vs 12ms / 6s vs 10ms)
- **Esqueci minha senha** com código 6 dígitos via email (TTL 15 min, throttle
  60s, bloqueio após 5 tentativas erradas)

### Autorização
- Páginas HTML protegidas via cookie + role check server-side
- API protegida via Bearer token + `require_role`
- Admin não pode resetar senha de outro admin (anti-sequestro)
- Admin não pode desativar outro admin
- Último admin do sistema não pode ser rebaixado/desativado

### Dados
- PDFs criptografados com **Fernet (AES)** client-side antes de subir ao R2
- Senha SMTP criptografada com `MASTER_ENCRYPTION_KEY`
- IPs pseudonimizados via HMAC-SHA256 (LGPD Art. 46)
- Anonimização irreversível de colaboradores desligados (Art. 16, I)
- Página `/privacidade` com aviso completo

### Upload de PDF — 4 camadas
1. **Body size limit no middleware** (55MB pra rotas de invoice, 1MB pra
   resto) — rejeita multipart absurdo via 413 sem nem chegar no parser.
   Antes, o limite de 5 arquivos era checado APÓS o parse, consumindo
   30s de CPU/memória num upload de 12×9MB. Pentest jun/2026 fechou.
2. **Magic bytes** (`%PDF-`) — bloqueia arquivos renomeados (`.exe` → `.pdf`)
3. **Detecção de JavaScript embutido** — bloqueia PDFs com `/JS`, `/JavaScript`,
   `/OpenAction` (vetores típicos de exploit)
4. **Sanitização de filename** — UUID + extensão (anti header injection)

### Validação de campos de invoice
- `amount`: `> 0` e `<= R$ 10 bi` com `decimal_places=2` estrito (antes,
  `1e308` era aceito e gravado como inteiro de 309 dígitos)
- `issue_date` e `due_date`: dentro de ±10 anos da data atual (antes,
  `9999-12-31` e `1800-01-01` passavam)
- `invoice_number`: `<= 50 chars`; campos texto têm `max_length` consistente
- `ValidationError` do Pydantic em rotas multipart agora vira **422** com
  `{campo}: {mensagem}` (antes vazava como 500, dando fingerprint pro atacante)

### Headers HTTP
- `Content-Security-Policy` restritivo (script-src `'self' https://cdn.jsdelivr.net`
  — jsdelivr liberado apenas para `jsQR` no scanner; sem `unsafe-inline`)
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security` (HSTS 1 ano)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(self), microphone=(), geolocation=()` —
  câmera liberada para a própria origem (necessária pro scanner do contas
  a pagar); microfone e geolocalização seguem bloqueados

### Endpoints administrativos desligados em PROD
- `/docs`, `/redoc`, `/openapi.json` retornam **404 em PROD** (antes vazavam
  spec de 73 endpoints com schemas Pydantic completos). DEV continua aberto.
- `/health/dependencies` exige Bearer ADMIN em PROD (antes revelava qual
  provider de email/R2 estava configurado pra qualquer um que perguntasse).
- `/health/live` e `/health/ready` continuam públicos pra orquestrador.

### CORS
- Em PROD: restrito ao domínio público do Railway
- Em DEV: aberto para facilitar testes locais

## Defesa contra admin malicioso (insider threat)

Modelo de ameaças assumido: **o admin do sistema não tem acesso ao Railway/banco**. Sob essa premissa, quatro camadas eliminam os ataques mais prováveis:

| Ataque | Defesa | Comportamento |
|---|---|---|
| Trocar SMTP pra interceptar reset de senha | SMTP fora da UI | Configuração SMTP/Resend vive em `.env`. Quem opera o Railway controla; quem tem login admin não enxerga. |
| Criar diretor fake pra fluxar fraude | Notificação peer | Todos os diretores ativos recebem email em segundos com nome do criador. |
| Desativar/encerrar diretor "do nada" | Janela de 24h | Em vez de aplicar, cria `PendingAdminAction`. Diretor + outros diretores recebem email + banner vermelho no dashboard com botão "Não foi autorizada". |
| Resetar senha de diretor pra logar como ele | Notificação imediata | Diretor afetado recebe email no ato da troca. |
| Editar `audit_logs` direto no banco | Hash chain | Cada linha contém SHA-256 da anterior + dos próprios campos. `GET /api/admin/audit-logs/verify-chain` detecta tampering. |

Variáveis de ambiente do envio de email (vivem só no Railway):

```bash
EMAIL_PROVIDER=RESEND   # SMTP | RESEND | DISABLED
RESEND_API_KEY=re_...
SMTP_FROM_EMAIL=nao-responder@economart.com.br
# (alternativa SMTP)
SMTP_HOST=...  SMTP_PORT=587  SMTP_USE_TLS=true
SMTP_USER=...  SMTP_PASSWORD=...
```

O que **não está coberto técnicamente** (exige controle humano):

- Dois admins colaborando — depende de RH e cota mínima de admins de times diferentes.
- Mesma pessoa controlando app + infra — depende de separação física de funções.
- Logs replicados fora do controle do operador da infra — recomendação futura.

Detalhes completos em [`docs/security.md`](docs/security.md#defesa-contra-admin-malicioso) e [`docs/domain-model.md`](docs/domain-model.md#defesa-contra-admin-malicioso-insider-threat).

## Setup local

### Pré-requisitos
- Python 3.12+
- Git

### Instalação

```bash
git clone https://github.com/guiolindo/Notas-despesas.git
cd Notas-despesas
pip install -r requirements.txt
```

### Variáveis de ambiente

Copie `.env.example` para `.env`:

```bash
cp .env.example .env
```

Edite com valores reais:

```env
DATABASE_URL=sqlite:///./economart.db

# Gere com: python -c "import secrets; print(secrets.token_hex(64))"
SECRET_KEY=<sua chave de 128 chars hex>

# Gere com: python generate_keys.py
MASTER_ENCRYPTION_KEY=<chave Fernet>

ENVIRONMENT=DEV

# Cloudflare R2 (opcional em dev — sem isso, fallback para uploads/ local)
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_ENDPOINT_URL=
R2_BUCKET_NAME=
```

### Rodar

```bash
python -m uvicorn app.main:app --reload --port 7145
```

Acesse [http://localhost:7145](http://localhost:7145).

**Login inicial**: `admin@economart.com` / `Admin@2024!`
(troca obrigatória no primeiro acesso).

> ⚠️ **Em produção, troque essa senha IMEDIATAMENTE após o primeiro deploy.**
> A credencial está hardcoded no código (`main.py:_ensure_admin_exists()`)
> pra facilitar bootstrap. `must_change_password=True` força a troca no
> primeiro login e desde jun/2026 a tentativa de "trocar pela mesma" é
> rejeitada, mas qualquer pessoa com acesso ao repositório conhece a
> credencial até a troca acontecer.

## Deploy no Railway

### 1. Criar serviços
- Adicione um plugin **PostgreSQL** no projeto
- Crie um serviço a partir do repo `guiolindo/Notas-despesas`

### 2. Variáveis do serviço web

| Variável | Valor |
|---|---|
| `DATABASE_URL` | Referência ao Postgres (`Add Reference` na UI do Railway) |
| `SECRET_KEY` | 128 chars hex |
| `MASTER_ENCRYPTION_KEY` | Chave Fernet (44 chars terminada em `=`) |
| `ENVIRONMENT` | `PROD` |
| `R2_ACCESS_KEY_ID` | Da API token do Cloudflare R2 |
| `R2_SECRET_ACCESS_KEY` | Da API token do Cloudflare R2 |
| `R2_ENDPOINT_URL` | `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | nome do bucket |

### 3. Configurações
- O `Procfile` e `railway.toml` já definem `gunicorn ... --preload`
- Healthcheck em `/health`
- Restart on failure (10 retries)

### 4. Storage R2
- Crie conta grátis em [dash.cloudflare.com](https://dash.cloudflare.com)
- R2 Object Storage → Create bucket
- Manage R2 API Tokens → Create Account API Token com Object Read & Write

### 5. Email (SMTP ou Resend) — configurado via variável de ambiente

Configuração de email **vive só no `.env`/painel do Railway**, não na UI do
admin (defesa contra admin malicioso interceptar reset de senha). Veja
[Defesa contra admin malicioso](#defesa-contra-admin-malicioso-insider-threat).

**Opção A — Resend** (recomendado em Railway, funciona sem desbloqueio):
- Conta grátis em [resend.com](https://resend.com)
- Crie uma API Key
- Adicione `EMAIL_PROVIDER=RESEND`, `RESEND_API_KEY=re_...`, `SMTP_FROM_EMAIL=...`

**Opção B — SMTP** (Gmail, Outlook, SendGrid):
- Crie conta Gmail dedicada
- Ative 2FA → gere App Password em [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Adicione `EMAIL_PROVIDER=SMTP`, `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`,
  `SMTP_USE_TLS=true`, `SMTP_USER=...`, `SMTP_PASSWORD=...`, `SMTP_FROM_EMAIL=...`

**Opção C — Desabilitar** (dev local sem email real):
- `EMAIL_PROVIDER=DISABLED` (sistema pula os envios silenciosamente)

## Configurações

Definidas em `app/config.py` (`pydantic-settings`), lidas de variáveis de
ambiente ou `.env`.

### Autenticação
| Setting | Default | Descrição |
|---|---|---|
| `SECRET_KEY` | (default inseguro) | Chave HMAC pra assinar JWT. **Obrigatória em PROD** (app não sobe). Gere com `python -c "import secrets; print(secrets.token_hex(64))"` |
| `ALGORITHM` | `HS256` | Algoritmo de assinatura do JWT |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | Validade do access token |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | Validade do refresh token (cookie HttpOnly) |
| `MAX_LOGIN_ATTEMPTS` | `5` | Tentativas antes de bloquear conta |
| `LOGIN_BLOCK_MINUTES` | `10` | Duração do bloqueio |

### Ambiente e dados
| Setting | Default | Descrição |
|---|---|---|
| `ENVIRONMENT` | `DEV` | `DEV` ou `PROD`. Em `PROD`: `/docs`/`/redoc`/`/openapi.json` desligam, cookies viram `Secure`, CORS restringe, `/health/dependencies` exige admin |
| `DATABASE_URL` | `sqlite:///./economart.db` | URL SQLAlchemy. Use Postgres em prod |
| `MASTER_ENCRYPTION_KEY` | (vazio) | Chave Fernet pra criptografar PDFs antes do upload. **Obrigatória em PROD**. Gere com `python generate_keys.py` |

### Storage (Cloudflare R2)
| Setting | Default | Descrição |
|---|---|---|
| `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | (vazio) | Credenciais R2 |
| `R2_ENDPOINT_URL` | (vazio) | `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | (vazio) | Nome do bucket. Vazio → fallback `uploads/` local (DEV) |

### Email
| Setting | Default | Descrição |
|---|---|---|
| `EMAIL_PROVIDER` | `SMTP` | `SMTP` \| `RESEND` \| `DISABLED` |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USE_TLS`, `SMTP_USER`, `SMTP_PASSWORD` | — | Credenciais SMTP. `SMTP_USE_TLS=true` usa STARTTLS na porta 587; `false` usa SSL direto na 465 |
| `RESEND_API_KEY` | (vazio) | Chave da API Resend (alternativa HTTP) |
| `SMTP_FROM_EMAIL`, `SMTP_FROM_NAME` | — | Remetente que aparece nos emails |

## Endpoints HTTP

Referência completa em [`docs/api-reference.md`](docs/api-reference.md).
Resumo:

### Públicos (sem auth)
| Método | Rota | O que faz |
|---|---|---|
| GET | `/` | Redireciona para `/dashboard` (ou `/login` se anônimo) |
| GET | `/login`, `/forgot-password`, `/reset-password`, `/change-password` | Páginas HTML de auth |
| GET | `/privacidade`, `/faq`, `/offline.html` | Páginas estáticas |
| GET | `/verify/{invoice_id}` | Versão pública da nota com nome mascarado (LGPD) |
| GET | `/health/live` | Liveness probe (sempre 200 se processo respira) |
| GET | `/health/ready` | Readiness probe (checa DB com `SELECT 1`) |
| GET | `/health/dependencies` | Status de R2/email — **PROD exige Bearer ADMIN** |
| POST | `/auth/login` | Devolve access token + cookie refresh HttpOnly |
| POST | `/auth/refresh` | Renova access via cookie refresh |
| POST | `/auth/forgot-password` | Envia código de 6 dígitos (resposta constante anti-enumeração) |
| POST | `/auth/reset-password` | Confirma código + senha nova |

### Autenticados (Bearer ou cookie)
**Sessão e perfil:**
| Método | Rota | Quem |
|---|---|---|
| GET | `/auth/me` | Qualquer usuário |
| POST | `/auth/logout` | Qualquer usuário (revoga access via `session_invalidated_at`) |
| POST | `/auth/change-password` | Qualquer usuário (rejeita senha igual à atual) |
| PUT | `/auth/me/availability` | MANAGER, DIRECTOR (modo férias) |

**Páginas HTML autenticadas** (role-gated):
- `/dashboard`, `/configuracoes`, `/alerts` — todos os perfis
- `/invoices`, `/invoices/new`, `/invoices/{id}`, `/invoices/{id}/edit` — EMPLOYEE+
- `/manager/queue`, `/manager/invoices/{id}` — MANAGER
- `/director/queue`, `/director/invoices/{id}` — DIRECTOR
- `/finance/queue`, `/finance/invoices/{id}` — FINANCE
- `/admin/users`, `/admin/users/new`, `/admin/users/{id}/edit`, `/admin/audit-logs`, `/admin/departments` — ADMIN
- `/contas-a-pagar/scanner` — CONTAS_A_PAGAR

**Notas fiscais** (`/api/invoices`):
| Método | Rota | Quem |
|---|---|---|
| GET | `/api/invoices/` | Qualquer perfil (filtros + paginação + `total_amount`) |
| POST | `/api/invoices/` | EMPLOYEE, MANAGER, DIRECTOR |
| GET | `/api/invoices/{id}` | Stakeholder da nota |
| PATCH | `/api/invoices/{id}` | Criador (só em RASCUNHO/REPROVADO) |
| DELETE | `/api/invoices/{id}` | Criador (só em RASCUNHO/REPROVADO) |
| POST | `/api/invoices/{id}/submit` | Criador (transição → AGUARDANDO_GESTOR ou _DIRETOR) |
| POST | `/api/invoices/{id}/cancel` | Criador (volta a RASCUNHO) |
| POST | `/api/invoices/{id}/review` | MANAGER (aprovar → diretor, ou reprovar) |
| POST | `/api/invoices/{id}/director-review` | DIRECTOR (aprovar → finance, ou reprovar) |
| POST | `/api/invoices/{id}/transfer-director` | DIRECTOR (repassa pra outro diretor) |
| POST | `/api/invoices/{id}/mark-paid` | FINANCE (gera PDF + grava status PAGO) |
| GET | `/api/invoices/{id}/print` | FINANCE, CONTAS_A_PAGAR, ADMIN (reimprime) |
| GET | `/api/invoices/{id}/attachment` | Stakeholder (legado, primeiro anexo) |
| GET | `/api/invoices/{id}/attachments/{att_id}` | Stakeholder |
| DELETE | `/api/invoices/{id}/attachments/{att_id}` | Criador |
| GET | `/api/invoices/{id}/comments` | Stakeholder (paginado) |
| POST | `/api/invoices/{id}/comments` | Stakeholder |
| GET | `/api/invoices/{id}/verify-full` | Stakeholder (versão completa do `/verify`) |
| GET | `/api/invoices/directors` | EMPLOYEE+ (lista pra seleção no submit) |
| GET | `/api/invoices/lookup-cnpj/{cnpj}` | Qualquer perfil (cache 180 dias) |

**Admin** (`/api/admin/*` — todos exigem ADMIN):
| Método | Rota | O que faz |
|---|---|---|
| GET, POST | `/users`, `/users/{id}` (GET/PUT) | CRUD de usuário |
| POST | `/users/{id}/reset-password` | Reset forçado (notifica titular) |
| POST | `/users/{id}/unlock` | Limpa lockout |
| POST | `/users/{id}/anonymize` | Pseudonimização irreversível (LGPD) |
| GET, POST, PUT, DELETE | `/departments`, `/departments/{id}` | CRUD de setor |
| GET | `/managers`, `/directors` | Listas pra selects do form de user |
| GET | `/audit-logs` | Lista paginada de auditoria |
| GET | `/audit-logs/verify-chain` | Valida hash chain (detecta tampering no DB) |
| POST | `/maintenance/purge-rejected` | Limpa reprovadas > 90 dias |

**Outros:**
| Método | Rota | Quem |
|---|---|---|
| GET | `/alerts/` | Qualquer perfil (5 buckets agregados) |
| GET | `/api/contas-a-pagar/stats` | CONTAS_A_PAGAR (badge "Conferidas hoje") |
| GET | `/api/pending-actions/me` | Qualquer perfil (ações administrativas pendentes contra mim) |
| GET | `/api/pending-actions/visible` | Quem pode revisar como peer (DIRECTOR/ADMIN) |
| POST | `/api/pending-actions/{id}/cancel` | Target ou peer |
| POST | `/api/pending-actions/{id}/confirm` | Peer (executa antes das 24h) |

### Desligados em PROD
- `/docs`, `/redoc`, `/openapi.json` — 404 quando `ENVIRONMENT=PROD` (pentest jun/2026 #SEC-1). DEV continua aberto pro Swagger.

## Estrutura do projeto

```
economart_notas/
├── app/
│   ├── main.py                      # FastAPI entry, middlewares, migrations
│   ├── config.py                    # Settings via pydantic-settings
│   ├── database.py                  # Engine SQLAlchemy + session
│   ├── middleware/
│   │   ├── observability.py         # Request ID + timing log
│   │   └── security.py              # CSP, HSTS, rate limit, body size limit
│   ├── models/                      # SQLAlchemy models
│   │   ├── users.py                 # User + UserRole + session_invalidated_at
│   │   ├── invoices.py              # FSM com 7 status
│   │   ├── invoice_attachments.py   # Anexos PDF (até 5/nota, criptografados)
│   │   ├── invoice_comments.py      # Thread de comentários
│   │   ├── approval_history.py      # Trilha imutável
│   │   ├── audit_logs.py            # Hash chain anti-tampering
│   │   ├── departments.py
│   │   ├── cnpj_cache.py            # Cache 180 dias do opencnpj.org
│   │   ├── email_queue.py           # Fila SMTP com retry exponencial
│   │   ├── pending_admin_actions.py # Janela 24h pra acoes peer
│   │   └── smtp_settings.py         # PasswordResetCode (SMTP virou env-only)
│   ├── routers/                     # Endpoints
│   │   ├── auth.py                  # /auth/* — login, refresh, logout, forgot/reset/change-password, me, availability
│   │   ├── admin.py                 # /api/admin/* — users, departments, audit-logs (+ verify-chain), managers, directors, maintenance/purge-rejected, anonymize
│   │   ├── invoices.py              # /api/invoices/* — CRUD, FSM (submit/cancel/review/director-review/transfer-director), mark-paid, attachments, comments, lookup-cnpj, directors
│   │   ├── pages.py                 # Páginas HTML com role guard (cookie + role check)
│   │   ├── alerts.py                # /alerts/ — agregado por bucket (vencidas, 72h, rejected, etc.)
│   │   ├── contas_a_pagar.py        # /api/contas-a-pagar/stats — badge "Conferidas hoje" no dashboard
│   │   ├── pending_actions.py       # /api/pending-actions/* — janela 24h pra acoes peer
│   │   └── print_routes.py          # /api/invoices/{id}/print + /verify/{id} público + /verify-full API
│   ├── schemas/                     # Pydantic
│   ├── security/
│   │   ├── dependencies.py          # get_current_user, require_role
│   │   ├── page_auth.py             # require_page_login/role
│   │   ├── hashing.py               # bcrypt + HMAC pseudonymize
│   │   └── jwt.py
│   ├── services/                    # Business logic
│   │   ├── invoice_service.py       # FSM, validações, triggers
│   │   ├── drive_service.py         # R2 storage (criptografia Fernet)
│   │   ├── document_service.py      # Mod 11 CPF/CNPJ + lookup opencnpj + masks LGPD
│   │   ├── email_service.py         # SMTP + Resend HTTP API + templates
│   │   ├── email_queue_service.py   # Fila com retry exponencial + worker async
│   │   ├── pdf_service.py           # Geração de comprovante (capa + QR + anexos)
│   │   └── alert_service.py
│   ├── static/
│   │   ├── css/main.css             # Design system unificado + tokens --role-*
│   │   ├── js/                      # vanilla, sem build (19 módulos)
│   │   │   ├── format.js, documents.js     # helpers puros
│   │   │   ├── core.js                     # Auth, apiFetch, UI helpers
│   │   │   ├── shell.js                    # login, initShell, configuracoes
│   │   │   ├── pdf-viewer.js, comments.js, password.js
│   │   │   ├── invoices-list.js, invoice-form.js, invoice-detail.js
│   │   │   ├── alerts.js, finance.js, review.js
│   │   │   ├── admin-users.js, admin-departments.js, admin-audit.js
│   │   │   ├── drawer.js                   # drawer lateral compartilhado
│   │   │   ├── dispatcher.js               # roteador DOMContentLoaded
│   │   │   ├── app.js                      # stub pós-refactor P2-1 v3
│   │   │   ├── dashboard-v2.js             # dashboard novo (só /dashboard)
│   │   │   ├── scanner.js                  # bipador + câmera (jsQR)
│   │   │   ├── verify.js                   # /verify público
│   │   │   ├── not-found.js                # countdown + redirect 404
│   │   │   └── offline.js                  # tela offline (PWA)
│   │   └── sw.js                    # Service Worker
│   │   └── img/
│   │       ├── logo.png
│   │       └── icons/               # 36 SVGs Lucide vendorizados (MIT)
│   └── templates/                   # Jinja2 com autoescape
│       ├── 404.html                 # Página amigável com countdown
│       ├── verify.html              # Verify público (LGPD mask + reveal)
│       ├── contas_a_pagar/scanner.html
│       └── ...
├── requirements.txt
├── Procfile                         # Gunicorn config Railway
├── railway.toml                     # Build/deploy config
└── .gitignore                       # Exclui .env, *.db, credentials.json, uploads/
```

## Convenções de código

- **Backend**: Python 3.12, type hints, snake_case
- **Datas**: armazenadas em UTC, exibidas no frontend em `America/Sao_Paulo`
- **IDs**: UUID4 string (36 chars)
- **Senhas**: nunca logadas, nunca expostas em GET — sempre bcrypt
- **Erros**: HTTPException com `status_code` e `detail` em PT-BR
- **Audit log**: toda ação importante registra em `audit_logs`
- **Histórico**: transições de invoice em `approval_history` (visível na UI)
- **Sem framework JS**: o frontend é vanilla pra reduzir superficie de ataque e dependências

## Mudanças recentes

Resumo das entregas das últimas semanas (commit-by-commit em
`git log --oneline`):

- **Pentest jun/2026 — 9 vulnerabilidades corrigidas** em 3 rounds:
  `/docs` em PROD desligado, `forgot-password` com tempo constante,
  `/health/dependencies` gated, login timing equalizado, logout revoga
  access token, body size limit no upload, amount/date com bounds,
  senha igual à atual rejeitada, ValidationError→422. Detalhes em
  [`docs/decisoes-2026-06-03.md`](docs/decisoes-2026-06-03.md).
- **Refactor completo do `app.js`** (P2-1 v3, 3712 linhas → 14 módulos
  pequenos) — `core.js`, `shell.js`, `pdf-viewer.js`, `drawer.js`, etc.
  Mantém o padrão "sem build" e backward-compat com bookmarks antigos.
  Plano em [`docs/plan-appjs-split-v3.md`](docs/plan-appjs-split-v3.md).

- **CPF/CNPJ obrigatório do fornecedor** com validação Mod 11 e autocomplete
  via opencnpj.org (cache 6 meses)
- **Página /verify pública com máscara LGPD** + revelação automática para
  quem participa do fluxo da nota (criador, gestor, diretor, financeiro,
  contas a pagar, admin)
- **Novo role CONTAS_A_PAGAR** (read-only + scanner)
- **Página /contas-a-pagar/scanner** com bipador e câmera (jsQR)
- **Dashboard refeito por perfil** — 4 layouts distintos (Admin, Employee,
  Aprovadores, Contas a Pagar)
- **Sistema de ícones Lucide vendorizado** (36 SVGs em `static/img/icons/`,
  renderizados via CSS mask para herdar `currentColor`)
- **Tokens de role** (`--role-admin`, `--role-manager`, etc.) com paleta
  institucional consistente
- **Página 404 amigável** com contagem regressiva e redirect inteligente
- **Critical CSS inline + View Transitions API + barra de progresso de
  navegação** — eliminam flash branco entre páginas
- **Login respeita `?next=`** (volta pro destino original com proteção
  anti open-redirect)
- **Documento `/privacidade` completo** com Aviso de Privacidade + Termos
  de Uso + Segurança da Informação (4 partes navegáveis)
- **Mensagens limpas** — sweep geral removendo jargão técnico ("token",
  "cache", "bucket", "transição inválida"). Substituídas por linguagem
  humana e instruções de ação.
- **"Encerrar conta" no admin** (substitui o antigo "Anonimizar LGPD") —
  pseudonimização irreversível, login permanentemente bloqueado, histórico
  preservado por exigência fiscal (5 anos CTN)

## Licença

Software proprietário Economart Atacadista. Uso interno.

---

**Suporte / dúvidas**: contato com o administrador do sistema.
