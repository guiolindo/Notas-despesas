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
- [Setup local](#setup-local)
- [Deploy no Railway](#deploy-no-railway)
- [Configurações](#configurações)
- [Estrutura do projeto](#estrutura-do-projeto)
- [Convenções de código](#convenções-de-código)

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
| Storage de PDFs | Cloudflare R2 (S3-compatible, criptografia client-side) |
| Email | SMTP via `smtplib` (Gmail App Password recomendado) |
| Auth | JWT (access 60min) + refresh token HttpOnly (7 dias) |
| Servidor | Gunicorn + Uvicorn workers |
| Deploy | Railway |

## Funcionalidades

### Para colaboradores
- Criar nota fiscal com upload de **até 5 PDFs** (nota + boletos + comprovantes,
  10 MB cada, 25 MB total). Viewer mostra todos os anexos mesclados.
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

### Para admin
- CRUD completo de usuários (com setor e gestor obrigatórios)
- CRUD de setores com designação de diretores
- Auditoria completa (filtros por ação, usuário, sucesso)
- **Configuração de email automático** — escolha entre SMTP (Gmail, Outlook,
  SendGrid) ou Resend (HTTP API, funciona em Railway sem desbloqueio)
- **Anonimização LGPD via botão na lista de usuários** (só para inativos não-admin)
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

## Perfis de usuário

| Role | Função |
|---|---|
| `ADMIN` | Acesso total. Gerencia usuários, setores e configuração do sistema |
| `EMPLOYEE` (Funcionário) | Cria notas e acompanha aprovação |
| `MANAGER` (Gestor) | Aprova/reprova notas do seu setor |
| `DIRECTOR` (Diretor) | Aprova/reprova após o gestor |
| `FINANCE` (Financeiro) | Lança notas aprovadas e gera comprovantes |

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
- JWT access token (60 min) + refresh token HttpOnly cookie (7 dias, secure em PROD)
- Rate limit de login: 5 tentativas → bloqueio 10 min (com email automático ao titular)
- Race condition prevenida com `SELECT FOR UPDATE` no PostgreSQL
- Refresh token revalida usuário no DB a cada uso (rebaixamento/desativação têm efeito imediato)
- **Tokens emitidos antes da última troca de senha são invalidados** — admin
  reseta senha → todas as sessões abertas do usuário caem
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

### Upload de PDF — 3 camadas
1. **Magic bytes** (`%PDF-`) — bloqueia arquivos renomeados (`.exe` → `.pdf`)
2. **Detecção de JavaScript embutido** — bloqueia PDFs com `/JS`, `/JavaScript`,
   `/OpenAction` (vetores típicos de exploit)
3. **Sanitização de filename** — UUID + extensão (anti header injection)

### Headers HTTP
- `Content-Security-Policy` restritivo (script-src 'self')
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `Strict-Transport-Security` (HSTS 1 ano)
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy` desabilitando câmera/microfone/geolocalização

### CORS
- Em PROD: restrito ao domínio público do Railway
- Em DEV: aberto para facilitar testes locais

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

Ou no Windows: dois cliques no `start.bat`.

Acesse [http://localhost:7145](http://localhost:7145).

**Login inicial**: `admin@economart.com` / `Admin@2024!`
(troca obrigatória no primeiro acesso).

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

### 5. Email SMTP (opcional, configurado depois pelo admin)
- Crie conta Gmail dedicada
- Ative 2FA → gere App Password em [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)
- Acesse `/admin/smtp` no sistema e preencha

## Configurações

| Setting | Default | Descrição |
|---|---|---|
| `ACCESS_TOKEN_EXPIRE_MINUTES` | 60 | Validade do access token |
| `REFRESH_TOKEN_EXPIRE_DAYS` | 7 | Validade do refresh token |
| `MAX_LOGIN_ATTEMPTS` | 5 | Tentativas antes de bloquear |
| `LOGIN_BLOCK_MINUTES` | 10 | Tempo de bloqueio após exceder |

## Estrutura do projeto

```
economart_notas/
├── app/
│   ├── main.py                      # FastAPI entry, middlewares, migrations
│   ├── config.py                    # Settings via pydantic-settings
│   ├── database.py                  # Engine SQLAlchemy + session
│   ├── middleware/
│   │   └── security.py              # CSP, HSTS, rate limit
│   ├── models/                      # SQLAlchemy models
│   │   ├── users.py
│   │   ├── invoices.py              # FSM com 7 status
│   │   ├── approval_history.py      # Trilha imutável
│   │   ├── audit_logs.py
│   │   ├── departments.py
│   │   └── smtp_settings.py         # Config SMTP + PasswordResetCode
│   ├── routers/                     # Endpoints
│   │   ├── auth.py                  # Login, refresh, forgot/reset password
│   │   ├── admin.py                 # /api/admin/* (users, depts, SMTP, audit)
│   │   ├── invoices.py              # /api/invoices/* (CRUD + transições FSM)
│   │   ├── pages.py                 # Páginas HTML com role guard
│   │   ├── alerts.py                # Alertas (vencendo, atrasadas)
│   │   └── print_routes.py          # Comprovante PDF + verify público
│   ├── schemas/                     # Pydantic
│   ├── security/
│   │   ├── dependencies.py          # get_current_user, require_role
│   │   ├── page_auth.py             # require_page_login/role
│   │   ├── hashing.py               # bcrypt + HMAC pseudonymize
│   │   └── jwt.py
│   ├── services/                    # Business logic
│   │   ├── invoice_service.py       # FSM, validações, triggers
│   │   ├── drive_service.py         # R2 storage (criptografia Fernet)
│   │   ├── email_service.py         # SMTP + templates
│   │   ├── pdf_service.py           # Geração de comprovante
│   │   └── alert_service.py
│   ├── static/
│   │   ├── css/main.css             # Design system unificado
│   │   ├── js/app.js                # Vanilla JS, SPA-like
│   │   └── img/logo.png
│   └── templates/                   # Jinja2 com autoescape
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

## Licença

Software proprietário Economart Atacadista. Uso interno.

---

**Suporte / dúvidas**: contato com o administrador do sistema.
