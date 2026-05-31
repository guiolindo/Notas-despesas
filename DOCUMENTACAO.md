# Documentação Técnica Completa — Economart Notas Fiscais

> **Arquivo de uso interno.** Não versionado (gitignored).
> Última atualização: 2026-05-25

---

## Sumário
1. [Arquitetura](#1-arquitetura)
2. [Modelo de dados](#2-modelo-de-dados)
3. [Camadas e responsabilidades](#3-camadas-e-responsabilidades)
4. [Endpoints completos](#4-endpoints-completos)
5. [Máquina de estados das notas](#5-máquina-de-estados-das-notas)
6. [Sistema de autenticação](#6-sistema-de-autenticação)
7. [Storage criptografado (R2)](#7-storage-criptografado-r2)
8. [Sistema de email](#8-sistema-de-email)
9. [Auditoria e LGPD](#9-auditoria-e-lgpd)
10. [Middleware e segurança](#10-middleware-e-segurança)
11. [Frontend (JS vanilla)](#11-frontend-js-vanilla)
12. [Templates e CSS](#12-templates-e-css)
13. [Migrations e versionamento de schema](#13-migrations-e-versionamento-de-schema)
14. [Deploy Railway — checklist completo](#14-deploy-railway--checklist-completo)
15. [Variáveis de ambiente](#15-variáveis-de-ambiente)
16. [Como debugar problemas comuns](#16-como-debugar-problemas-comuns)
17. [Decisões arquiteturais (ADRs)](#17-decisões-arquiteturais-adrs)
18. [Alertas contextuais na nota](#18-alertas-contextuais-na-nota)
19. [Anti-reenvio de nota reprovada sem mudança](#19-anti-reenvio-de-nota-reprovada-sem-mudança)
20. [Invalidação de JWT pós-troca de senha](#20-invalidação-de-jwt-pós-troca-de-senha)
20.5. [Auto-delete de notas reprovadas (90 dias)](#205-auto-delete-de-notas-reprovadas-90-dias)
21. [Multi-anexo (até 5 PDFs por nota)](#21-multi-anexo-até-5-pdfs-por-nota)
21.5. [Modo férias (auto-pausa de recebimento)](#215-modo-férias-auto-pausa-de-recebimento)
21.6. [Director self-submit (criar nota própria → Financeiro)](#216-director-self-submit-criar-nota-própria--financeiro)
21.7. [Categoria "Rejeitadas" no dashboard de alertas](#217-categoria-rejeitadas-no-dashboard-de-alertas)
21.8. [Exclusão manual de nota reprovada](#218-exclusão-manual-de-nota-reprovada)
21.9. [Anonimização via botão na UI (LGPD)](#219-anonimização-via-botão-na-ui-lgpd)
21.10. [PDF anti-malware (3 camadas)](#2110-pdf-anti-malware-3-camadas)
22. [Roadmap conhecido (pendências)](#22-roadmap-conhecido-pendências)

---

## 1. Arquitetura

```
┌───────────────────────────────────────────────────────────────┐
│                       CLIENT (BROWSER)                         │
│  - HTML estático servido por Jinja2                           │
│  - JS vanilla (app.js) — sem framework                        │
│  - Comunicação via fetch() + Bearer token (JWT)               │
└──────────────────────┬────────────────────────────────────────┘
                       │ HTTPS
┌──────────────────────▼────────────────────────────────────────┐
│  RAILWAY (Gunicorn + 2 Uvicorn workers, --preload)            │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │  FastAPI app                                             │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌──────────────────┐   │ │
│  │  │ Middlewares │ │   Routers   │ │     Services     │   │ │
│  │  │             │ │             │ │                  │   │ │
│  │  │ • CSP       │ │ • auth      │ │ • invoice_       │   │ │
│  │  │ • HSTS      │ │ • admin     │ │ • drive_ (R2)    │   │ │
│  │  │ • CORS      │ │ • invoices  │ │ • email_         │   │ │
│  │  │ • RateLimit │ │ • pages     │ │ • pdf_           │   │ │
│  │  └─────────────┘ │ • alerts    │ │ • alert_         │   │ │
│  │                  │ • print     │ └──────────────────┘   │ │
│  │                  └─────────────┘                         │ │
│  │  ┌──────────────────────────────────────────────────┐   │ │
│  │  │  SQLAlchemy 2.x ORM                              │   │ │
│  │  └────────────────────┬─────────────────────────────┘   │ │
│  └───────────────────────┼─────────────────────────────────┘ │
└──────────────────────────┼───────────────────────────────────┘
                           │ pool_pre_ping + pool_recycle 5min
              ┌────────────▼──────────┐         ┌─────────────────┐
              │  PostgreSQL (Railway) │         │  Cloudflare R2  │
              │                       │         │  (PDFs Fernet)  │
              └───────────────────────┘         └─────────────────┘
                           ▲
              ┌────────────┴──────────┐
              │  SMTP (Gmail+TLS:587) │ ← envia emails
              └───────────────────────┘
```

### Componentes externos
- **Railway**: hosting + PostgreSQL + variáveis de ambiente
- **Cloudflare R2**: armazenamento de PDFs (S3-compatible, free tier 10GB)
- **Gmail SMTP**: envio de notificações (App Password obrigatório)

### Filosofia
- **Monolito pragmático** — uma só aplicação FastAPI, deploy único
- **Frontend embutido** — Jinja2 + JS vanilla, sem build step
- **Stateless por request** — sessão via JWT em header, refresh em cookie HttpOnly
- **Background jobs leves** — emails enviados síncronos dentro do request (FastAPI BackgroundTasks seria upgrade futuro)
- **Segurança por padrão** — todo endpoint exige role check explícito

---

## 2. Modelo de dados

### Tabelas

#### `users`
| Coluna | Tipo | Notas |
|---|---|---|
| id | VARCHAR(36) PK | UUID4 |
| name | VARCHAR(255) | NOT NULL |
| email | VARCHAR(255) UNIQUE | Lowercased no save |
| hashed_password | VARCHAR(255) | bcrypt |
| role | ENUM | ADMIN/EMPLOYEE/MANAGER/DIRECTOR/FINANCE |
| manager_id | FK users.id | Só EMPLOYEE usa |
| is_active | BOOLEAN | default TRUE |
| created_at | DATETIME | UTC |
| last_login | DATETIME | UTC |
| login_attempts | INTEGER | Resetado em login OK |
| blocked_until | DATETIME | UTC + 10min após 5 falhas |
| must_change_password | BOOLEAN | TRUE no primeiro login |
| password_changed_at | DATETIME | UTC — tokens emitidos antes são rejeitados (invalida sessão pós-reset) |
| department_id | FK departments.id | Obrigatório exceto ADMIN |
| submit_directly_to_director | BOOLEAN | Pula gestor |
| unavailable_for_notes | BOOLEAN | Modo férias (default FALSE) — diretor/gestor não recebe notas novas |

#### `departments`
| Coluna | Tipo |
|---|---|
| id | VARCHAR(36) PK |
| name | VARCHAR UNIQUE |
| description | TEXT |

#### `director_departments` (many-to-many)
| Coluna | Tipo |
|---|---|
| user_id | FK users.id |
| department_id | FK departments.id |

#### `invoices`
| Coluna | Tipo | Notas |
|---|---|---|
| id | VARCHAR(36) PK | UUID4 |
| invoice_number | VARCHAR(100) | texto livre |
| issue_date | DATE | data de emissão |
| due_date | DATE | >= issue_date |
| description | TEXT | sanitized |
| bank_details | TEXT | opcional |
| amount | NUMERIC(10,2) | em R$ |
| status | ENUM | ver FSM |
| created_by_id | FK users.id | sempre preenchido |
| manager_id | FK users.id | preenchido ao submeter |
| director_id | FK users.id | preenchido ao aprovar/escolher |
| finance_id | FK users.id | preenchido no lançamento |
| drive_file_id | VARCHAR(255) | object key no R2 ou "local:uuid" |
| drive_file_name | VARCHAR(255) | nome original |
| encryption_key_enc | TEXT | Fernet key cifrada com MASTER_KEY |
| created_at | DATETIME | UTC |
| submitted_at | DATETIME | UTC |
| manager_reviewed_at | DATETIME | UTC |
| director_reviewed_at | DATETIME | UTC |
| paid_at | DATETIME | UTC quando lançada |
| print_drive_file_id | VARCHAR(255) | (não usado atualmente) |
| printed_at | DATETIME | UTC da última impressão |
| printed_by_id | FK users.id | autor da última impressão |
| description_at_rejection | TEXT | Snapshot da descrição na hora da reprovação — reenvio requer descrição diferente |

#### `approval_history`
Trilha imutável. Cada transição vira uma linha. Visível na UI (timeline).

| Coluna | Tipo |
|---|---|
| id | VARCHAR(36) PK |
| invoice_id | FK |
| user_id | FK |
| action | ENUM ApprovalAction |
| comment | TEXT |
| timestamp | DATETIME UTC |
| ip_address | VARCHAR(45) HMAC pseudonymized |
| source_port | INTEGER |

`ApprovalAction`:
- CREATED — funcionário criou
- SUBMITTED — funcionário enviou
- CANCELLED — funcionário cancelou envio
- APPROVED_MANAGER / REJECTED_MANAGER
- APPROVED_DIRECTOR / REJECTED_DIRECTOR
- MARKED_PAID — lançada (auto após 1ª impressão)
- PRINTED — só registra na 1ª impressão (reimpressões não logam)

#### `audit_logs`
Log técnico para auditoria fiscal/segurança. NÃO visível na UI normal — só na página `/admin/audit-logs`.

| Coluna | Tipo |
|---|---|
| id | VARCHAR(36) PK |
| user_id | FK users.id (pode ser NULL — sistema) |
| action | VARCHAR(100) — ex: CREATE_USER, LOGIN_FAIL |
| resource_type | VARCHAR — User, Invoice, etc |
| resource_id | VARCHAR — ID do recurso afetado |
| ip_address | VARCHAR pseudonymized |
| source_port | INTEGER |
| http_method | VARCHAR(10) |
| user_agent | TEXT |
| timestamp | DATETIME UTC |
| success | BOOLEAN |
| detail | TEXT |

#### `smtp_settings` (singleton, id=1)
| Coluna | Tipo | Notas |
|---|---|---|
| id | INTEGER PK | sempre 1 |
| provider | VARCHAR(20) | `SMTP` ou `RESEND` |
| smtp_host | VARCHAR(255) | ex: smtp.gmail.com (ignorado se Resend) |
| smtp_port | INTEGER | 587 default (ignorado se Resend) |
| smtp_user | VARCHAR(255) | email do remetente (ignorado se Resend) |
| smtp_password_enc | TEXT | Fernet(MASTER_KEY). SMTP: senha. RESEND: API key |
| smtp_from_email | VARCHAR(255) | from header |
| smtp_from_name | VARCHAR(255) | "Economart Notas" |
| use_tls | BOOLEAN | true (port 587, ignorado se Resend) |
| enabled | BOOLEAN | false até admin habilitar |
| updated_at | DATETIME UTC | |
| updated_by_id | FK users.id | |

**Por que Resend?** Railway bloqueia portas SMTP em todos os planos abaixo
de Pro. Resend usa HTTPS (api.resend.com) — passa pelo firewall normalmente.
Grátis até 3000 emails/mês.

#### `password_reset_codes`
Códigos de 6 dígitos para "esqueci minha senha". TTL 15 min.

| Coluna | Tipo |
|---|---|
| id | VARCHAR(36) PK |
| user_id | FK |
| code_hash | VARCHAR — bcrypt do código plain |
| expires_at | DATETIME UTC |
| used_at | DATETIME UTC (null = ativo) |
| created_at | DATETIME UTC |

### Índices em produção
Migration cria automaticamente (em PG, IF NOT EXISTS):
- `idx_invoices_status`, `idx_invoices_created_by`, `idx_invoices_manager`, `idx_invoices_director`, `idx_invoices_number`
- `idx_users_role`, `idx_users_active`
- `idx_audit_user`, `idx_audit_timestamp`
- `idx_history_invoice`
- `idx_pwreset_user`

---

## 3. Camadas e responsabilidades

### `app/main.py`
Entry point. Faz:
- Carrega `templates` Jinja2 com autoescape explícito
- Cria `app = FastAPI(...)`
- Roda `Base.metadata.create_all()` (cria tabelas novas em DB virgem)
- Chama `_ensure_admin_exists()` (admin padrão se DB vazio)
- Roda `_run_schema_migrations()` (ALTER TABLE para colunas novas em DB antigos)
- Monta `/static`
- Adiciona middlewares: `SecurityHeadersMiddleware`, `RateLimitMiddleware`, `CORSMiddleware`
- Inclui routers
- `GET /health` → `{"status": "ok"}` para healthcheck do Railway

### `app/config.py`
`Settings` via pydantic-settings. Lê `.env` + `os.environ`.

### `app/database.py`
- `_build_engine()` — cria SQLAlchemy engine
  - Reescreve `postgres://` → `postgresql://` (Railway usa o legado)
  - PostgreSQL: `pool_pre_ping=True`, `pool_recycle=300` (evita SSL EOF do Railway)
  - SQLite: `check_same_thread=False`
- `SessionLocal` — factory de sessões
- `Base` — declarative base
- `get_db()` — dependency injection

### `app/models/`
Definições SQLAlchemy declarativas. Cada arquivo = 1 entidade.

### `app/routers/`
Endpoints FastAPI. Cada arquivo é um `APIRouter`.

### `app/services/`
Lógica de negócio pura. Routers chamam services. Services chamam ORM e bibliotecas externas. **Services nunca dependem de Request/Response do FastAPI** — passam IP/porta como parâmetros.

### `app/security/`
- `jwt.py` — `create_access_token`, `create_refresh_token`, `decode_token`
- `hashing.py` — `hash_password`, `verify_password`, `pseudonymize_ip`
- `dependencies.py` — `get_current_user`, `require_role` (para APIs)
- `page_auth.py` — `require_page_login`, `require_page_role` (para HTML, via cookie)

### `app/middleware/security.py`
- `SecurityHeadersMiddleware` — injeta CSP, HSTS, etc em toda resposta
- `RateLimitMiddleware` — rate limit em `/auth/login` (10 req/min/IP, em memória)

### `app/schemas/`
Modelos Pydantic para request/response. Garantia de tipos na API.

---

## 4. Endpoints completos

### Públicos (sem auth)
- `GET /` → redirect `/dashboard`
- `GET /health` → status do servidor
- `GET /login` → página de login
- `GET /forgot-password` → form esqueci senha
- `GET /reset-password` → form código + nova senha
- `GET /privacidade` → aviso LGPD
- `GET /verify/{invoice_id}` → página pública de verificação (QR code do comprovante leva aqui)
- `POST /auth/login` — { email, password } → access_token + refresh cookie
- `POST /auth/refresh` — Cookie → novo access_token (revalida user no DB)
- `POST /auth/logout` — limpa refresh cookie
- `POST /auth/forgot-password` — { email } → 200 sempre (anti-enumeração), envia código se user existir
- `POST /auth/reset-password` — { email, code, new_password } → senha atualizada

### Autenticados (qualquer role)
- `GET /dashboard` — página inicial
- `GET /change-password` — form trocar senha
- `POST /auth/change-password` — { current_password, new_password }
- `GET /auth/me` — dados do user logado
- `GET /alerts` + `GET /alerts/` (API) — notas vencendo/atrasadas (criadas pelo user)
- `GET /invoices` — página listagem
- `GET /invoices/new` — form criar
- `GET /invoices/{id}` — página detalhe
- `GET /invoices/{id}/edit` — form editar (só rascunho/reprovada)
- `GET /api/invoices/` — JSON paginado com filtros (search, from/to_date, due_from/to, min/max_amount, status, created_by)
- `POST /api/invoices/` — multipart (data + PDF file) → cria
- `PATCH /api/invoices/{id}` — multipart → atualiza rascunho
- `DELETE /api/invoices/{id}` — só rascunho
- `POST /api/invoices/{id}/submit?director_id=X` — envia para gestor/diretor
- `POST /api/invoices/{id}/cancel` — volta para RASCUNHO
- `GET /api/invoices/{id}` — JSON do detalhe
- `GET /api/invoices/{id}/attachment` — baixa PDF (decriptado)
- `GET /api/invoices/directors` — lista diretores disponíveis com flag de compatibilidade

### Para MANAGER
- `GET /manager/queue` — fila de aprovação
- `GET /manager/invoices/{id}` — detalhe (mesma página, contexto diferente)
- `POST /api/invoices/{id}/review` — { action: APPROVE|REJECT, comment, director_id }

### Para DIRECTOR
- `GET /director/queue`
- `GET /director/invoices/{id}`
- `POST /api/invoices/{id}/director-review` — { action: APPROVE|REJECT, comment }

### Para FINANCE
- `GET /finance/queue` — fila APROVADO + filtros
- `GET /finance/invoices/{id}`
- `GET /api/invoices/{id}/print` — gera PDF do comprovante; 1ª chamada marca como PAGO/Lancado

### Para ADMIN (`/api/admin/*` requer role ADMIN via Bearer)
- `GET /admin/users` → HTML
- `GET /admin/users/new` → HTML form
- `GET /admin/users/{id}/edit` → HTML form
- `GET /admin/departments` → HTML
- `GET /admin/audit-logs` → HTML
- `GET /admin/smtp` → HTML config SMTP

- `GET /api/admin/users` → lista JSON
- `POST /api/admin/users` — cria
- `GET /api/admin/users/{id}` — detalhe
- `PUT /api/admin/users/{id}` — atualiza
- `POST /api/admin/users/{id}/reset-password` — admin reseta (não pode em outro admin)
- `POST /api/admin/users/{id}/unlock` — destrava conta bloqueada
- `POST /api/admin/users/{id}/anonymize` — LGPD (só usuários inativos não-admin)
- `GET /api/admin/managers` — lista gestores (para selects)
- `GET /api/admin/directors` — lista diretores
- `GET /api/admin/departments` → JSON
- `POST /api/admin/departments` — cria
- `PUT /api/admin/departments/{id}` — atualiza
- `DELETE /api/admin/departments/{id}` — só se vazio
- `GET /api/admin/audit-logs?page=N&action=X&user_id=Y&success=true` — paginado
- `GET /api/admin/smtp` — config SEM senha
- `PUT /api/admin/smtp` — atualiza (senha em branco mantém atual)
- `POST /api/admin/smtp/test` — envia email de teste pro admin logado

---

## 5. Máquina de estados das notas

Definida em `invoice_service.py` → `FSM_TRANSITIONS` + `_assert_transition`.

```python
FSM_TRANSITIONS = {
    "submit_to_manager": (RASCUNHO, AGUARDANDO_GESTOR),
    "submit_to_director": (RASCUNHO, AGUARDANDO_DIRETOR),
    "cancel": (None, RASCUNHO),  # múltiplas origens
    "manager_approve": (AGUARDANDO_GESTOR, AGUARDANDO_DIRETOR),
    "manager_reject": (AGUARDANDO_GESTOR, REPROVADO_GESTOR),
    "director_approve": (AGUARDANDO_DIRETOR, APROVADO),
    "director_reject": (AGUARDANDO_DIRETOR, REPROVADO_DIRETOR),
    "mark_paid": (APROVADO, PAGO),
}
```

### Regras de visibilidade (`_can_view`)
- ADMIN: tudo
- EMPLOYEE: só `created_by_id == user.id`
- MANAGER: notas onde `manager_id == user.id` OU `created_by.manager_id == user.id`
- DIRECTOR: `director_id == user.id` OU notas APROVADO/PAGO (histórico)
- FINANCE: APROVADO/PAGO

### Quem pode fazer o quê
| Ação | Quem | Condição |
|---|---|---|
| Criar nota | qualquer logado | sempre |
| Submeter | criador | `status == RASCUNHO` |
| Cancelar | criador | status AGUARDANDO_* e nenhuma aprovação prévia |
| Editar | criador | status RASCUNHO ou REPROVADO_* |
| Excluir | criador | status RASCUNHO |
| Aprovar gestor | manager_id da nota | status AGUARDANDO_GESTOR |
| Aprovar diretor | director_id da nota | status AGUARDANDO_DIRETOR |
| Imprimir/Lançar | FINANCE ou ADMIN | status APROVADO ou PAGO |

---

## 6. Sistema de autenticação

### Tokens
- **Access token** — JWT HS256, payload `{sub: user_id, role: USER_ROLE, type: "access", exp: +60min}`
- **Refresh token** — JWT HS256, payload similar mas `type: "refresh", exp: +7d`

### Storage
- Access: `localStorage` (cliente lê em cada `apiFetch`)
- Refresh: cookie HttpOnly + SameSite=strict + Secure(PROD)

### Fluxo
1. `POST /auth/login` → retorna access em body + seta refresh em cookie
2. JS guarda access em localStorage
3. Cada request manda `Authorization: Bearer <access>`
4. Quando expira, JS chama `POST /auth/refresh` (cookie vai automaticamente)
5. Servidor revalida user no DB (is_active, blocked_until) e retorna novo access

### Bloqueio
- 5 tentativas de login com senha errada → `blocked_until = now + 10min`
- Email é enviado ao titular (best-effort)
- AuditLog não é criado para LOGIN_FAIL (decisão consciente — privacy)

### Esqueci minha senha
1. `POST /auth/forgot-password { email }` → resposta sempre 200
2. Se user existe: gera código 6 dígitos, salva hash bcrypt com TTL 15 min, envia email
3. Códigos antigos do mesmo user são invalidados (`used_at = now`)
4. User insere código em `POST /auth/reset-password { email, code, new_password }`
5. Backend percorre códigos ativos do user, valida com bcrypt.verify, marca como usado, atualiza senha

---

## 7. Storage criptografado (R2)

### Fluxo de upload
1. Backend recebe `UploadFile`
2. Lê bytes na memória (max 10 MB)
3. Gera Fernet key aleatória (`file_key = Fernet.generate_key()`)
4. Criptografa o PDF: `encrypted = Fernet(file_key).encrypt(bytes)`
5. Criptografa a `file_key` com a `MASTER_ENCRYPTION_KEY`: `key_enc = Fernet(MASTER).encrypt(file_key)`
6. boto3 sobe `encrypted` no R2 com key `<uuid>.enc`
7. Salva no DB: `drive_file_id=<uuid>.enc`, `encryption_key_enc=base64(key_enc)`

### Fluxo de download
1. Recebe `drive_file_id` do DB
2. Se prefix `local:`: lê de `uploads/{uuid}.enc`
3. Senão: `boto3.get_object(Bucket=R2_BUCKET, Key=drive_file_id)`
4. Decriptografa a `file_key`: `file_key = Fernet(MASTER).decrypt(b64decode(key_enc))`
5. Decriptografa o PDF: `pdf = Fernet(file_key).decrypt(encrypted)`
6. Stream resposta para cliente

### Fallback local
Sem R2 configurado (dev local), salva em `uploads/<uuid>.enc` no disco. Marca com prefix `local:` no DB.

### Substituição de anexo (edit)
Faz upload do NOVO primeiro. Só depois deleta o antigo. Se upload falhar, o antigo continua intacto (sem nota órfã).

---

## 8. Sistema de email

### Configuração
`SmtpSettings` no DB (singleton). Senha criptografada com Fernet(MASTER_KEY).
Admin acessa `/admin/smtp` para configurar.

### Templates HTML
Em `email_service.py`, função `_wrap(content)` aplica CSS inline (compatibilidade com clientes de email):
- Brand laranja Economart no topo
- Container card centralizado, max-width 520px
- Botão laranja
- Footer "mensagem automática, não responda"

### Triggers (best-effort, não bloqueia fluxo)
| Evento | Função | Quem recebe |
|---|---|---|
| Nota enviada para gestor | `_notify_approver(db, manager, invoice)` | Gestor do setor |
| Nota enviada direto ao diretor | `_notify_approver(db, director, invoice)` | Diretor escolhido |
| Gestor aprova | `_notify_approver(db, director, invoice)` | Diretor |
| Diretor aprova | `_notify_finance_team(db, invoice)` | TODOS users FINANCE ativos |
| Gestor/Diretor reprova | `_notify_rejection(db, invoice, rejector, reason)` | Criador da nota |
| 5 falhas de login | `template_account_blocked` | Titular da conta |
| Esqueci senha | `template_password_reset_code` | Solicitante |

### Robustez
- `send_email` é wrapped em try/except — exceção NÃO propaga
- Se SMTP `enabled=False`, retorna sem tentar
- Se config incompleta, retorna sem tentar
- Logs em `logger.info/warning/error`

### Anti-enumeração
`/auth/forgot-password` SEMPRE retorna 200 com mensagem genérica, independente de o email existir ou não. Isso impede atacante de descobrir emails cadastrados.

---

## 9. Auditoria e LGPD

### Pseudonimização de IP
- `pseudonymize_ip(ip)` retorna `"ip:" + hmac_sha256(SECRET_KEY, ip)[:16]`
- IP original NUNCA é armazenado em texto puro
- Conformidade LGPD Art. 46 (medidas de segurança)
- Compatível com Marco Civil Art. 15 (rastreabilidade) quando combinado com `source_port`

### Anonimização (Art. 18 c/c Art. 16, I)
- Endpoint `POST /api/admin/users/{id}/anonymize`
- Só funciona se `is_active == False` (desligamento confirmado)
- ADMIN não pode ser anonimizado
- Substitui: `name = "Colaborador Desligado <8-char-suffix>"`, `email = "purged-<uuid>@desligado.local"`, `hashed_password = "PURGED_PREVENT_LOGIN_<uuid>"` (login impossível), `manager_id = None`
- Histórico de aprovações é PRESERVADO (obrigação legal CTN Art. 173 — 5 anos fiscais)

### Aviso de privacidade
- Página `/privacidade` (pública)
- Tabela de dados coletados, finalidade, base legal LGPD, retenção
- Direitos do titular (Art. 18)
- Canal de contato

### Retenção
| Dado | Prazo |
|---|---|
| Histórico de aprovações | 5 anos (CTN Art. 173) |
| PDFs de notas | 5 anos |
| IP pseudonimizado / timestamps | mínimo 6 meses (Marco Civil) |
| Identificação civil (nome, email) | até 2 anos pós-desligamento ou anonimização |

---

## 10. Middleware e segurança

### `SecurityHeadersMiddleware`
Injeta em TODA resposta:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: SAMEORIGIN` (permite iframe do PDF interno)
- `X-XSS-Protection: 1; mode=block`
- `Referrer-Policy: strict-origin-when-cross-origin`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Strict-Transport-Security: max-age=31536000; includeSubDomains`
- `Content-Security-Policy`:
  ```
  default-src 'self';
  style-src 'self' 'unsafe-inline' https://fonts.googleapis.com;
  font-src https://fonts.gstatic.com;
  img-src 'self' data:;
  script-src 'self';
  frame-src 'self' blob:;
  object-src 'none';
  base-uri 'self'
  ```

### `RateLimitMiddleware`
Memória local — 10 tentativas/min por IP em `POST /auth/login`. Acima disso retorna 429.

### CORS
- DEV: `["*"]`
- PROD: lê `RAILWAY_PUBLIC_DOMAIN` do env, usa `[https://<domain>]`
- `allow_credentials=False` (token vai em Bearer header, não em cookie)

---

## 11. Frontend (JS vanilla)

### Estrutura `app.js`
- Top: utils (formatDate, formatCurrency, escapeHtml, apiFetch)
- Middle: por página (initDashboard, initInvoicesList, initInvoiceForm, etc.)
- Bottom: page dispatcher (`document.body.dataset.page`)

### `apiFetch`
Wrapper de `fetch` que:
- Adiciona `Authorization: Bearer <token>` se logado
- Adiciona `Content-Type: application/json` se body não for FormData
- Em 401: limpa auth + redireciona pra `/login`
- Em 5xx: mostra mensagem amigável, log detalhado no console
- Em erro de validação Pydantic: extrai primeiro erro do array `detail`

### `Auth`
Singleton em `localStorage`:
- `Auth.getToken()`, `Auth.getUser()`, `Auth.setSession(token, user)`, `Auth.clear()`

### Páginas
Dispatched via `data-page="..."` no `<body>`. Cada template tem ID único.

### Refresh seletivo
Em vez de `location.reload()`, várias telas fazem `apiFetch(...).then(updated => renderX(updated))` para preservar scroll/estado.

### Drawer
Componente lateral à direita que abre detalhe de nota sem mudar de URL (animação CSS). Substitui o modal antigo.

---

## 12. Templates e CSS

### Jinja2
- Autoescape habilitado para .html, .htm, .xml
- `escapeHtml` é função JS espelhada (filtra XSS no client-side)
- Inheritance via `base.html` (layout) → cada página `extends`

### Design system (`static/css/main.css`)
- **Paleta**: laranja `#F47920` (primário), azul `#1B4F8A` (secundário)
- **Tokens**: `--space-xs..2xl`, `--radius-sm..lg`, `--shadow-sm..lg`
- **Tipografia**: Inter (Google Fonts), 15px base
- **Mobile-first**: breakpoints em 768px e 480px
- **Acessibilidade**: focus-visible em todos os interativos, contrastes WCAG AA

### Estados de cor
- Status RASCUNHO → cinza
- AGUARDANDO_* → azul
- REPROVADO_* → vermelho
- APROVADO → verde
- PAGO/Lancada → verde forte (+ bold)

---

## 13. Migrations e versionamento de schema

**Não usa Alembic.** Estratégia: `Base.metadata.create_all` (cria tabelas novas) + `_run_schema_migrations` (ALTER TABLE idempotente para colunas novas em DBs existentes).

### `_run_schema_migrations` em `main.py`
- Detecta dialect (postgresql vs sqlite)
- Em PG: usa `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- Em SQLite: tenta sem IF NOT EXISTS, captura exceção (coluna já existe)
- Cria índices via `CREATE INDEX IF NOT EXISTS`
- Roda DROP COLUMN IF EXISTS para colunas legacy (só PG)

**Toda coluna nova adicionada ao modelo PRECISA entrar nesta migration**, senão deploy em DB antigo quebra com UndefinedColumn.

---

## 14. Deploy Railway — checklist completo

### Setup inicial
1. Repo `guiolindo/Notas-despesas` no GitHub
2. New project no Railway → Deploy from GitHub repo
3. Add service: PostgreSQL (plugin)
4. No service web → Variables → adicionar todas (ver seção 15)
5. Settings → Generate Domain

### Procfile + railway.toml
```
# Procfile
web: gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT --preload

# railway.toml
[deploy]
startCommand = "..."
healthcheckPath = "/health"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
```

`--preload` é **crítico**: app carrega no master, workers fazem fork. Evita race condition em `create_all` e `_ensure_admin_exists`.

### Caso de bug conhecido (já resolvido)
Em 23/05/2026: variáveis configuradas no serviço NÃO eram injetadas no container (bug do Railway com runtime V2). Solução foi **deletar e recriar o serviço web** mantendo o PostgreSQL plugin. As variáveis precisaram ser readicionadas e funcionaram.

---

## 15. Variáveis de ambiente

| Variável | Onde | Obrigatória | Notas |
|---|---|---|---|
| `DATABASE_URL` | DB | sim | SQLAlchemy URL. Railway: `postgresql://...` |
| `SECRET_KEY` | JWT + HMAC | sim | 128 chars hex via `secrets.token_hex(64)` |
| `MASTER_ENCRYPTION_KEY` | PDFs + SMTP | sim | Fernet key (44 chars terminando em `=`) via `python generate_keys.py` |
| `ENVIRONMENT` | flags | sim | `DEV` ou `PROD` |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | JWT | não | default 60 |
| `REFRESH_TOKEN_EXPIRE_DAYS` | JWT | não | default 7 |
| `MAX_LOGIN_ATTEMPTS` | bloqueio | não | default 5 |
| `LOGIN_BLOCK_MINUTES` | bloqueio | não | default 10 |
| `R2_ACCESS_KEY_ID` | R2 | não em dev | sem isso, fallback local |
| `R2_SECRET_ACCESS_KEY` | R2 | conjunto com a anterior | |
| `R2_ENDPOINT_URL` | R2 | conjunto | `https://<account>.r2.cloudflarestorage.com` |
| `R2_BUCKET_NAME` | R2 | conjunto | |
| `RAILWAY_PUBLIC_DOMAIN` | CORS | auto-injetada | Railway preenche, usado no CORS em PROD |

SMTP NÃO usa env vars — vem do DB (configurado via UI).

---

## 16. Como debugar problemas comuns

### "SECRET_KEY com valor padrão inseguro" no Railway
Variáveis não estão sendo injetadas. Recriar o serviço mantendo o PostgreSQL.

### "sqlite3.IntegrityError" no Railway
DATABASE_URL não está sendo lida (mesma causa acima) — app cai no default SQLite.

### "Race condition em _ensure_admin_exists"
`--preload` no gunicorn resolve. Já está nos arquivos.

### "SSL error: unexpected eof while reading" (PG)
Conexão idle morre. Solução: `pool_pre_ping=True` + `pool_recycle=300` em `database.py`. Já aplicado.

### PDF não abre / "Este conteúdo está bloqueado" (Edge)
CSP precisava de `frame-src 'self' blob:`. Já aplicado.

### "Erro ao carregar diretores"
Roteamento conflitante (pages.py capturando `/invoices/directors`). Resolvido movendo API para `/api/invoices/*`.

### Email não envia
Verifique:
1. `/admin/smtp` tem `enabled=true`
2. Senha SMTP está salva (testar com botão "Enviar email de teste")
3. Para Gmail: 2FA ativado + App Password (não senha da conta)
4. Logs do servidor: `[email]` (info/warning/error)

### Time travel — horário 3h adiantado
Datetime sem timezone serializado sem `Z`. Verificar se serializer usa `_utc_iso()` / `_as_utc()`.

---

## 17. Decisões arquiteturais (ADRs)

### ADR-001: Sem framework JS
Optei por vanilla JS por:
- Reduz superfície de ataque (sem CVEs de dependências)
- Build step zero (deploy só copia arquivos)
- Equipe pequena consegue manter
- Performance superior em conexões lentas

Trade-off: código mais verboso, sem hot reload, sem componentes reusáveis nativos.

### ADR-002: PostgreSQL > SQLite em produção
- SQLite não suporta `SELECT FOR UPDATE` (race condition em login)
- SQLite tem único writer (gargalo)
- PostgreSQL no Railway é grátis para começar

### ADR-003: Cloudflare R2 > Google Drive > AWS S3
- Google Drive: service account NÃO tem cota de armazenamento (falhou em produção)
- AWS S3: tráfego de saída pago
- Cloudflare R2: gratuito até 10GB, S3-compatible, sem egress

### ADR-004: Email enviado síncrono (não BackgroundTasks)
Por simplicidade. Trade-off: request fica ~500ms mais lento quando envia email. Aceitável para volume atual (poucas notas/dia). Upgrade futuro: usar `BackgroundTasks` ou fila externa.

### ADR-005: Sem Alembic
Migrations manuais em `_run_schema_migrations` (idempotentes). Por:
- Curva de aprendizado menor para a equipe
- Migrações são quase sempre `ADD COLUMN` ou `CREATE INDEX`
- Alembic é overkill para um schema com ~7 tabelas

Trade-off: migrations complexas (ex: ALTER TYPE de enum) seriam difíceis. Aceitar limitação.

### ADR-006: JWT + Cookie híbrido
- Access em localStorage (cliente lê facilmente)
- Refresh em cookie HttpOnly (XSS não rouba)
Trade-off: dois mecanismos pra manter. Vantagem: refresh é seguro.

---

## 18. Alertas contextuais na nota

Endpoint `GET /api/invoices/{id}` retorna campo `alerts: list[str]`. Computado
em `_compute_invoice_alerts` no router. Lógica:

| Condição | Mensagem |
|---|---|
| `issue_date` em mês anterior ao atual | "Nota emitida em mes anterior — envio atrasado pode comprometer prazo fiscal." |
| `due_date < hoje` (não PAGO/REPROVADO) | "Vencimento ja passou ha X dia(s). Risco de juros/multa." |
| `due_date == hoje` (não PAGO/REPROVADO) | "Vence hoje — prioridade maxima." |
| `due_date - hoje < 3 dias` (não PAGO/REPROVADO) | "Vencimento em X dia(s) — menos de 72h. Acelere a aprovacao." |

Frontend renderiza via `renderInvoiceAlerts(invoice, containerId)` que insere
banner amarelo (`alert-warning`) antes do container alvo. Aplicado em:
- `renderInvoiceDetail` (página `/invoices/{id}`)
- `_renderDrawerContent` (drawer das listagens)

Visível para todos os papéis que conseguem ver a nota (criador, gestor,
diretor, financeiro).

---

## 19. Anti-reenvio de nota reprovada sem mudança

Coluna `invoices.description_at_rejection` armazena a descrição no momento
da reprovação (`manager_review REJECT` ou `director_review REJECT`).

Quando o criador chama `POST /api/invoices/{id}/submit` em status
`REPROVADO_GESTOR` ou `REPROVADO_DIRETOR`, `submit_invoice` compara:
- Se `invoice.description == invoice.description_at_rejection` → 400 com
  "Edite a descricao antes de reenviar a nota."

No reenvio bem-sucedido, o snapshot é limpo (`= None`) — próxima reprovação
toma novo snapshot.

Por que apenas descrição? Decisão de produto: forçar o criador a explicitar
**o que mudou** sem complicar o modelo. 1 caractere já basta (sinal de
intenção, não diff técnico).

---

## 20. Invalidação de JWT pós-troca de senha

Coluna `users.password_changed_at`. Atualizada em:
- `/auth/change-password` (troca voluntária)
- `/auth/reset-password` (código por email)
- `/api/admin/users/{id}/reset-password` (reset por admin)

`get_current_user` (em `dependencies.py`) compara o `iat` do JWT com
`password_changed_at`. Se token foi emitido ANTES da troca:
- Retorna 401 "Sessao expirada (senha foi alterada). Faca login novamente."

Impacto:
- Admin reseta senha → atacante com token roubado é deslogado na próxima request
- Usuário troca a própria senha → todas as outras sessões caem (incluindo a atual)
- Aceitação: pequena fricção (precisa logar de novo) em troca de segurança real

---

## 20.5. Auto-delete de notas reprovadas (90 dias)

Notas em status `REPROVADO_GESTOR` ou `REPROVADO_DIRETOR` há mais de 90 dias
são automaticamente removidas. Implementado em
`invoice_service.purge_old_rejected_invoices()`.

**Quando roda:**
- No **startup** do app (após migrations e admin seed)
- Endpoint manual: `POST /api/admin/maintenance/purge-rejected` (admin only)

**O que apaga:**
- Linha do `Invoice` (cascade → attachments + approval_history)
- Arquivos no R2 (best-effort — se R2 cair, arquivo vira órfão mas DB segue limpo)

**O que NÃO apaga:**
- Notas `APROVADO`/`PAGO`: obrigação fiscal (CTN 5 anos)
- Notas `AGUARDANDO_*`: em fluxo ativo
- AuditLog: a entrada `AUTO_DELETE_REJECTED` é registrada com o `resource_id`
  da nota antes de apagar (rastreabilidade preservada)

**Aviso na UI:** A partir do dia 76 (14 dias para apagar), aparece banner amarelo
no detalhe da nota: "Esta nota sera removida automaticamente em X dia(s)."

---

## 21. Multi-anexo (até 5 PDFs por nota)

Adicionado em 2026-05-24. Antes cada `Invoice` tinha 1 PDF nas próprias colunas
(`drive_file_id`, `drive_file_name`, `encryption_key_enc`). Agora suporta lista.

### Modelo
Nova tabela `invoice_attachments`:
| Coluna | Tipo |
|---|---|
| id | UUID PK |
| invoice_id | FK invoices.id (cascade delete) |
| drive_file_id | object key no R2 |
| drive_file_name | nome original sanitizado |
| encryption_key_enc | Fernet key cifrada com MASTER |
| size_bytes | INTEGER |
| uploaded_at | DATETIME UTC |
| uploaded_by_id | FK users.id |

Relacionamento: `Invoice.attachments` (ordenado por uploaded_at).

As colunas antigas em `invoices` continuam por compat mas não são mais usadas
(podem ser removidas numa migration futura).

### Limites
- `MAX_ATTACHMENTS_PER_INVOICE = 5`
- `MAX_TOTAL_ATTACHMENT_BYTES = 25 MB` (10 MB por arquivo individual)
- Cada arquivo passa pelos checks de segurança independentes (magic, JS, OpenAction)

### Endpoints
- `POST /api/invoices/` aceita `files=[...]` multipart (list)
- `PATCH /api/invoices/{id}` aceita `files=[...]` — ADICIONA aos existentes (não substitui)
- `GET /api/invoices/{id}/attachment` (compat) — baixa o 1º anexo
- `GET /api/invoices/{id}/attachments/{att_id}` — baixa um específico
- `DELETE /api/invoices/{id}/attachments/{att_id}` — remove individual
  - Exige nota em status editável (rascunho/reprovado)
  - Bloqueia se for o último anexo (nota precisa ter pelo menos 1)

### UI
- Form: `<input type="file" multiple>` no drop-zone. Mostra "N arquivos: a.pdf, b.pdf..."
- Edição: lista anexos atuais com link de download + botão "Remover" por anexo
- Detalhe/drawer: 1º anexo abre no iframe principal. Demais ficam abaixo como
  links de download (lista compacta)

### PDF de comprovante
`generate_print_pdf` concatena na ordem: **Capa do Economart + cada anexo em
ordem de upload**. Se algum anexo falhar (R2 fora, chave inválida), pula esse
e continua — comprovante segue válido com os outros.

### Sanitização de nome
`_sanitize_attachment_name`:
- Remove path (só basename)
- Permite `\w \. \- \( \)` e espaço — substitui resto por `_`
- Limita 120 chars
- Garante extensão `.pdf` no final

Preserva legibilidade ("nota_fornecedor.pdf") sem permitir injection
("../../etc/passwd").

---

## 21.5. Modo férias (auto-pausa de recebimento)

Coluna `users.unavailable_for_notes` (BOOLEAN, default FALSE).

### Quem pode ativar
- `MANAGER` ou `DIRECTOR`
- Endpoint: `PUT /auth/me/availability` (body: `{unavailable: bool}`)
- UI: página `/configuracoes` → card "Recebimento de notas" → toggle

### Comportamento quando ativo
- `get_available_directors()` filtra usuários com flag = True
- Funcionários não conseguem mais escolhê-los ao enviar novas notas
- `_get_director()` rejeita com 400 se chegar request manipulada
- **Notas já atribuídas continuam visíveis** pra eles aprovarem
- Banner amarelo no topo de toda página: "Voce esta indisponivel para
  receber novas notas. [Reativar]"
- Admin assigning a um setor continua vendo todos (configuração estrutural)

### Reativar
Toggle off em `/configuracoes` — toma efeito imediato; próxima nota
pode ser enviada pra ele.

---

## 21.6. Director self-submit (criar nota própria → Financeiro)

Diretor pode criar e enviar nota direto pro Financeiro sem precisar de
outro aprovador (caso de despesa própria ou do setor).

### Backend (`_do_submit`)
```python
if user.role == UserRole.DIRECTOR:
    invoice.status = InvoiceStatus.APROVADO
    invoice.director_id = user.id
    invoice.director_reviewed_at = now
    _add_history(... ApprovalAction.SUBMITTED ...)
    _add_history(... ApprovalAction.APPROVED_DIRECTOR ...
                 comment="Enviada diretamente ao Financeiro pelo proprio diretor")
    _add_audit("DIRECTOR_SELF_SUBMIT", ...)
    _notify_finance_team(...)
```

### UI
- DIRECTOR vê botão "Nova Nota" em `/invoices`
- Form esconde picker de diretor (não escolhe a si próprio)
- Botão de submit vira "Criar e Enviar ao Financeiro"

### Visibilidade
- `_can_view` e `_query_visible_invoices` para DIRECTOR:
  - Notas com `director_id == user.id` OR `created_by_id == user.id`
- Isolamento entre setores preservado: outros diretores não veem
- Financeiro vê normalmente (status = APROVADO)

---

## 21.7. Categoria "Rejeitadas" no dashboard de alertas

`/alerts/` agora retorna 5 categorias (não 4):
- `overdue` — vencidas em fluxo ativo
- `due_72h` — vencimento próximo em fluxo ativo
- `old_emission` — emissão > mês atual em fluxo ativo
- **`rejected`** — notas reprovadas (só do **criador**)
- `pending_review` — aguardando aprovação do usuário atual (manager/director/finance)

`total_alerts` inclui `rejected_count`. Stat card "Reprovadas (suas)" e
seção dedicada na página de Alertas.

Status `REPROVADO_*` foram **removidos** da lista `not_paid` interna —
não geram mais ruído em overdue/due_72h/old_emission.

---

## 21.8. Exclusão manual de nota reprovada

`delete_invoice` agora aceita status:
- `RASCUNHO` (já aceitava)
- `REPROVADO_GESTOR` (novo)
- `REPROVADO_DIRETOR` (novo)

Botão "Excluir" aparece na lista, detalhe e drawer para essas notas.
Confirmação simples ("Excluir esta nota?"), sem alarme extra.

Cascade delete:
- Anexos no R2 (best-effort, falha não bloqueia)
- `approval_history` (cascade DB)
- Linha do `invoices`
- AuditLog `DELETE_INVOICE` preservado (rastreio mesmo após apagar)

Coexiste com o auto-delete 90 dias — usuário pode apagar antes se quiser.
Aprovadas/Pagas **nunca** são apagáveis (CTN 5 anos).

---

## 21.9. Anonimização via botão na UI (LGPD)

Endpoint `POST /api/admin/users/{id}/anonymize` agora tem botão na lista:
- Aparece **apenas** para usuário inativo + não-admin + não o próprio admin
- `btn-danger` na cor vermelha
- Confirmação detalhada explica:
  - Substituição irreversível de nome/email/senha
  - Usuário nunca mais loga
  - Histórico fiscal preservado (CTN 5 anos)
  - Ação não pode ser desfeita

### Fluxo correto
1. Admin clica em "Desativar" no usuário
2. Após confirmação, botão "Anonimizar (LGPD)" aparece
3. Admin clica e confirma — registro vira `Colaborador Desligado XXXXXXXX`

### O que acontece no DB
```python
user.name = f"Colaborador Desligado {suffix_8_chars}"
user.email = f"purged-{uuid}@desligado.local"
user.hashed_password = f"PURGED_PREVENT_LOGIN_{uuid}"  # nunca casa com bcrypt
user.manager_id = None  # desvincula
# is_active permanece False
# id, role, department_id, historico de notas — preservados
```

---

## 21.10. PDF anti-malware (3 camadas)

Em `_read_pdf_uploads()` + `_check_pdf_safety()`:

| Camada | Bloqueia | Custo |
|---|---|---|
| Magic bytes (`%PDF-`) | Arquivo renomeado (.exe, .zip → .pdf) | <1ms |
| Filename UUID-based | Header injection no Content-Disposition | <1ms |
| pypdf parse + detect | `/JS`, `/JavaScript`, `/OpenAction` (auto-exec) | 30-150ms |

Falha de parsing (PDF corrompido): assume legítimo (atacante teria que
enviar PDF válido com payload — aí cai nos checks). Falha do pypdf não
bloqueia upload pra evitar falsos positivos em PDFs reais com pequenos
defeitos.

---

## 22. Roadmap conhecido (pendências)

### Curto prazo (fácil)
- [ ] Adicionar `supplier` e `cnpj` ao modelo `Invoice` (precisa de migration + UI form)
- [ ] Backup automático do DB (Railway tem opção paga)
- [ ] Index full-text no `description` (PostgreSQL `tsvector`)

### Médio prazo
- [ ] DateTime(timezone=True) nas colunas (precisa migration arriscada)
- [ ] Background queue para emails (Celery + Redis ou rq)
- [ ] Export CSV/Excel de relatórios financeiros
- [ ] Notificação push no navegador (Service Worker)

### Longo prazo
- [ ] Multi-tenant (suporte a múltiplas empresas no mesmo deploy)
- [ ] 2FA obrigatório para ADMIN
- [ ] Webhooks para integrar com ERP
- [ ] App mobile (React Native ou PWA mais sofisticado)

### Não implementado por decisão
- ❌ Soft delete em users — anonimização LGPD já cobre o caso
- ❌ Versionamento de invoices — `approval_history` já registra mudanças relevantes
- ❌ Comments em invoices — fluxo de aprovação já tem comentários

---

## Apêndice A: Comandos úteis

```bash
# Rodar local
python -m uvicorn app.main:app --reload --port 7145

# Gerar SECRET_KEY
python -c "import secrets; print(secrets.token_hex(64))"

# Gerar MASTER_ENCRYPTION_KEY
python generate_keys.py

# Resetar admin (apaga DB local)
rm economart.db && python -m uvicorn app.main:app

# Conectar no Postgres do Railway
psql "$DATABASE_URL"

# Ver logs Railway
railway logs --service web

# Verificar Cloudflare R2
aws s3 ls --endpoint-url="$R2_ENDPOINT_URL" s3://<bucket>
```

## Apêndice B: SQL diagnóstico

```sql
-- Notas atrasadas (vencimento passado e ainda não pagas)
SELECT invoice_number, due_date, amount, status
FROM invoices
WHERE due_date < CURRENT_DATE AND status NOT IN ('PAGO');

-- Usuários sem setor (provavelmente bug ou criação anterior à validação)
SELECT id, name, email, role
FROM users
WHERE department_id IS NULL AND role != 'ADMIN';

-- Tentativas de login recentes
SELECT user_id, action, ip_address, timestamp, success
FROM audit_logs
WHERE action LIKE '%LOGIN%'
ORDER BY timestamp DESC LIMIT 50;

-- Volume de notas por mês
SELECT date_trunc('month', created_at) AS mes,
       COUNT(*) AS qtd,
       SUM(amount) AS total
FROM invoices
GROUP BY 1 ORDER BY 1 DESC;
```

---

## Apêndice C: Mudanças desde a versão anterior

Resumo das decisões técnicas das últimas semanas (detalhes completos no
histórico do git em `main`).

### 22. CPF/CNPJ obrigatório do fornecedor

Colunas novas em `invoices`: `supplier_document` (só dígitos, 11 ou 14),
`supplier_document_type` ("CPF"/"CNPJ"), `supplier_name`, `supplier_legal_name`.

**Validação Mod 11** em `app/services/document_service.py` — algoritmo
oficial da Receita. Usado tanto no Pydantic (`InvoiceCreate.validate_supplier_document`) quanto no frontend (`validateCPF`/`validateCNPJ` em `app.js`).

**Lookup automático de CNPJ** via `lookup_cnpj(db, cnpj)`:
- Bate em `https://api.opencnpj.org/<cnpj>` com `urllib.request`.
- Cache local na tabela `cnpj_cache` (model `CnpjCache`), TTL 180 dias.
- Frontend chama `GET /api/invoices/lookup-cnpj/<cnpj>` após Mod 11 passar.
- A origem cache/API **não é exposta na UI** (só log interno).

### 23. /verify público com máscara LGPD

`print_routes.py::verify_invoice` renderiza sempre mascarado via:
- `mask_name()` — corta cada palavra >2 chars em 3 letras + `***`, preservando preposições (de, da, do) e siglas (S/A, LTDA).
- `mask_cpf()`, `mask_cnpj()` — só primeiros e últimos dígitos.

Novo endpoint **`GET /api/invoices/{id}/verify-full`** (Bearer auth) retorna
dados completos somente se `_user_has_invoice_access`:
- ADMIN, FINANCE, CONTAS_A_PAGAR — sempre
- Demais: precisam ser `created_by_id`, `manager_id` ou `director_id`.

Frontend (`static/js/verify.js`) detecta `localStorage.access_token` e
chama o endpoint. Quatro estados em `.verify-banner`: info / loading /
success / warn (com "Entrar com outra conta").

### 24. Role CONTAS_A_PAGAR

Novo valor no `UserRole`. Migration via `ALTER TYPE userrole ADD VALUE
IF NOT EXISTS 'CONTAS_A_PAGAR'` em `_run_schema_migrations`.

`_can_view`/`_query_visible_invoices` liberam todas as notas. Reimpressão
permitida só quando `status == PAGO` — primeira impressão (que dispara
`mark-paid`) continua exclusiva do FINANCE.

Endpoint dedicado `GET /api/contas-a-pagar/stats` retorna
`{conferred_today: N}` — janela rolante de 24h em `ApprovalHistory.PRINTED`
pelo usuário logado.

### 25. Scanner QR (/contas-a-pagar/scanner)

Template `contas_a_pagar/scanner.html` + `static/js/scanner.js`. Dois modos:

- **Bipador**: input texto com auto-submit (Enter ou debounce 350ms).
- **Câmera**: `getUserMedia({facingMode:'environment'})` + jsQR via CDN.
  Mensagens de erro traduzidas por `DOMException.name`
  (`NotAllowedError`, `NotFoundError`, `NotReadableError`).

`extractInvoiceId()` aceita link `/verify/<id>`, URL absoluta ou UUID.

CSP ajustada: `script-src 'self' https://cdn.jsdelivr.net`,
`Permissions-Policy: camera=(self)`.

### 26. Encerramento de conta (substitui "Anonimizar LGPD")

Renomeado em toda a UI. Backend mantém endpoint `POST /api/admin/users/{id}/anonymize` por compatibilidade.

`_user_payload` retorna `is_anonymized` (email termina em `@desligado.local`).
`PUT /admin/users/{id}`, `POST .../reset-password` e `POST .../anonymize`
retornam 400 se já anonimizado.

Frontend: linha com `row-anonymized`, badge cinza "encerrada", nenhuma
ação de identidade renderizada.

### 27. Dashboard adaptado por perfil

`templates/dashboard.html` com bloco condicional por `current_user.role`.
Quatro ramos:

| Role | Hero | Quick actions | Alertas root |
|---|---|---|---|
| ADMIN | Gerenciar usuários | Setores · Auditoria · Email | `#dashboard-alerts-admin` |
| EMPLOYEE | Nova nota | Minhas · Buscar | `#dashboard-alerts-employee` |
| MANAGER / DIRECTOR / FINANCE | Revisar fila / Aprovar / Lançar | Nova · Buscar · Minhas | `#dashboard-alerts-approver` |
| CONTAS_A_PAGAR | Abrir scanner (F2) | Buscar · Conferidas hoje | `#dashboard-alerts-cap` |

`static/js/dashboard-v2.js`: arrays declarativos (`CAP_SPECS`, `ADMIN_SPECS`,
`EMPLOYEE_SPECS`, `APPROVER_SPECS`) + `renderAlerts(rootSel, alerts, specs)`
genérico (no-op se o root não existir). Endpoints em paralelo via
`Promise.allSettled`. Reusa helpers globais de `app.js` (`apiFetch`,
`escapeHtml`, `formatCurrency`, `formatDate`, `statusBadge`, `hourInBR`).

### 28. Sistema de ícones Lucide vendorizado

36 SVGs em `static/img/icons/` (MIT). Renderizados via **CSS mask**:

```css
.icon {
  display: inline-block; width: 1em; height: 1em;
  background-color: currentColor;
  -webkit-mask: var(--mask, none) center / contain no-repeat;
          mask: var(--mask, none) center / contain no-repeat;
}
.icon-pencil { --mask: url('/static/img/icons/pencil.svg'); }
```

Herda `currentColor`, CSP-safe (zero inline), cacheável.

### 29. Tokens de role

```css
--role-admin:          #153F6E;
--role-manager:        #1B4F8A;
--role-director:       #0E7490;  /* teal — era roxo #7C3AED, fora da paleta */
--role-finance:        #D86112;
--role-contas-a-pagar: #F47920;
--role-employee:       #6B7280;
```

`.role-chip` (tipografia) + `.role-{slug}` (cor). JS faz
`role.toLowerCase().replace(/_/g, '-')` pra casar `CONTAS_A_PAGAR` com
`.role-contas-a-pagar`.

### 30. Página 404 amigável

Handler global em `main.py` distingue navegação web de API por prefixo
(`/api/`, `/auth/`, `/alerts/`, `/admin/`, `/health` → JSON; resto →
template).

`templates/404.html` standalone (login-page layout) + `static/js/not-found.js`:
detecta `access_token`, escolhe destino (`/dashboard` se logado, `/login`
se anônimo), countdown 3s + botão "Ir agora" que cancela o timer.

### 31. UX de transição entre páginas (sem flash branco)

Duas causas eliminadas:

1. HTML renderizava antes do `main.css` chegar → flash de bg padrão.
2. `#app-layout` tinha `visibility:hidden` até JS rodar → mais flash.

Fixes em `base.html`:
- Critical CSS inline no `<head>` (cores do shell antes do stylesheet).
- Removido `visibility:hidden`.
- `@view-transition { navigation: auto; }` em CSS (Chrome/Edge 126+, Safari 18.2+).
- Barra `#nav-progress` (2px laranja, top) no clique em links internos.
- Animação `.content` (fade+slide 220ms) como fallback.

### 32. Login respeita ?next=

`getSafeNextParam()` lê `?next=` com sanitização anti open-redirect:
- só caminhos internos (começa com `/`, não `//`)
- bloqueia loop em `/login` e `/change-password`

Prioridade: `must_change_password` > `next` válido > `/dashboard`.

### 33. Documento /privacidade reformulado

Sumário navegável em 4 partes: Aviso de Privacidade, Termos de Uso,
Segurança da Informação, Contato e Atualizações. CSS dedicado
`.legal-doc`.

### 34. Sweep de jargão técnico

| Antes | Agora |
|---|---|
| "Token invalido" / "Refresh token ausente" | "Sessao expirada. Faca login novamente." |
| "Usuario anonimizado (LGPD)" | "Esta conta foi encerrada" |
| "Transicao invalida para status XYZ" | "Esta acao nao pode ser feita na nota neste momento." |
| "Falha ao montar anexos" | "Nao foi possivel abrir os anexos desta nota." |
| "Dados preenchidos (cache)" | "Dados do fornecedor preenchidos." |
| "Bucket overdue / pending_review" | mensagens humanas com instrução |
| "page deve ser >= 1" | "Numero de pagina invalido." |
| "Falha ao acessar camera: NotAllowedError" | traduzido por `DOMException.name` |
| "QR lido mas nao parece uma nota: \<raw\>" | "QR lido, mas nao parece ser de uma nota fiscal." |

Pluralização correta: "1 nota vencida" em vez de "1 notas vencidas".

### 35. .gitignore

`DOCUMENTACAO.md` saiu do gitignore — agora está versionada no repo.

---

**FIM da documentação técnica.**
