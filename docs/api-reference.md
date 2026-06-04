# Referência da API

Endpoints principais agrupados por área. Para a documentação
interativa completa, suba o app e acesse `/docs` (Swagger UI
gerado pelo FastAPI).

## Convenções

- Todos os endpoints autenticados esperam
  `Authorization: Bearer <access_token>` no header
- O `access_token` vem de `POST /auth/login` ou
  `POST /auth/refresh`
- Endpoints de página HTML usam autenticação via
  cookie HttpOnly `refresh_token` (page guard)
- Resposta de erro padrão: `{"detail": "mensagem"}` com HTTP
  4xx ou 5xx apropriado
- 409 com payload estruturado (ver duplicate detection abaixo)
- 422 para erros de validação Pydantic com formato padrão
- Todos os endpoints respondem com header `X-Request-ID` para
  correlação de logs

## Autenticação

### `POST /auth/login`

Login com email + senha.

**Body**:
```json
{
  "email": "user@example.com",
  "password": "senha"
}
```

**Resposta 200**:
```json
{
  "access_token": "eyJ...",
  "token_type": "bearer",
  "user": {
    "id": "...",
    "name": "Maria",
    "role": "MANAGER",
    "email": "...",
    "must_change_password": false,
    "submit_directly_to_director": false
  }
}
```

Cookie `refresh_token` (HttpOnly, SameSite=Strict, 7 dias) também
setado.

**Erros**:
- 401: email ou senha inválidos
- 403: conta inativa, bloqueada por tentativas, ou em janela de bloqueio
- 429: rate-limit (10 tentativas em 60s)

### `POST /auth/refresh`

Renova o access token usando o cookie de refresh.

**Body**: vazio. Cookie `refresh_token` é lido automaticamente.

**Resposta 200**:
```json
{ "access_token": "eyJ...", "token_type": "bearer" }
```

**Erros**:
- 401: cookie ausente, inválido, expirado, ou anterior à última
  troca de senha (apaga cookie via Set-Cookie no header)
- 403: conta bloqueada

### `POST /auth/logout`

Apaga o cookie de refresh.

### `GET /auth/me`

Dados do usuário logado.

**Resposta 200**:
```json
{
  "id": "...",
  "email": "...",
  "name": "...",
  "role": "MANAGER",
  "department_id": "...",
  "must_change_password": false,
  "submit_directly_to_director": false,
  "unavailable_for_notes": false,
  "substitute_director_id": null,
  "substitute_manager_id": null,
  "last_login": "2026-06-03T20:30:00+00:00"
}
```

Se `must_change_password=true`, adiciona `action_required: "change_password"`.

### `POST /auth/change-password`

Troca a própria senha.

**Body**:
```json
{
  "current_password": "atual",
  "new_password": "nova"
}
```

Política: nova senha precisa ter 8+ chars, com letra e número.

### `POST /auth/forgot-password`

Solicita código de recuperação por email.

**Body**: `{"email": "..."}`

Sempre responde 200 com mensagem genérica
("se o email existir, código enviado") — sem oráculo de
existência de conta.

Rate-limit: 5 requests em 600s.

### `POST /auth/reset-password`

Troca senha usando código recebido por email.

**Body**:
```json
{
  "email": "...",
  "code": "123456",
  "new_password": "..."
}
```

Rate-limit: 8 requests em 600s.

### `PUT /auth/me/availability`

Marca/desmarca indisponibilidade (modo férias).

**Body**:
```json
{
  "unavailable": true,
  "substitute_director_id": "uuid-do-substituto",
  "substitute_manager_id": null
}
```

Apenas MANAGER e DIRECTOR podem chamar. O backend aceita só o
campo correspondente ao role.

---

## Notas fiscais

### `GET /api/invoices/`

Lista notas visíveis para o usuário, paginadas.

**Query params**:

| Param | Tipo | Default | Descrição |
|---|---|---|---|
| `status` | string | null | Filtrar por status (RASCUNHO, AGUARDANDO_GESTOR, ...) |
| `page` | int | 1 | Página |
| `per_page` | int | 20 | Itens por página (máx 100) |
| `search` | string | null | Busca em número, descrição, fornecedor |
| `from_date`/`to_date` | date | null | Faixa de data de emissão |
| `due_from`/`due_to` | date | null | Faixa de vencimento |
| `min_amount`/`max_amount` | float | null | Faixa de valor |
| `created_by` | string | null | Nome do criador (busca parcial) |
| `supplier` | string | null | Nome ou documento do fornecedor |
| `department_id` | string | null | Filtrar por setor |
| `fields` | string | full | `light` usa loader leve (sem anexos/histórico) |

**Resposta 200**:
```json
{
  "items": [ /* InvoiceResponse */ ],
  "total": 247,
  "page": 1,
  "per_page": 20,
  "total_amount": 1234567.89
}
```

### `POST /api/invoices/`

Cria nova nota. **Multipart/form-data** (não JSON, por causa dos
anexos PDF).

**Form fields**:

| Campo | Tipo | Obrigatório |
|---|---|---|
| `invoice_number` | string | sim |
| `issue_date` | date (YYYY-MM-DD) | sim |
| `due_date` | date | sim |
| `description` | string (10-2000 chars) | sim |
| `amount` | decimal | sim |
| `supplier_document` | string (CPF/CNPJ, máscara opcional) | sim |
| `supplier_name` | string | não |
| `supplier_legal_name` | string | não |
| `bank_details` | string | não |
| `submit_now` | bool | não (default true) |
| `director_id` | string | só se `submit_directly_to_director` |
| `files` | files (1-5 PDFs, máx 10MB cada, 25MB total) | sim |

Apenas EMPLOYEE, MANAGER e DIRECTOR podem criar notas.

**Resposta 201**: objeto `InvoiceResponse` completo.

### `GET /api/invoices/{id}`

Detalhe da nota com histórico completo, anexos, comentários.

### `PATCH /api/invoices/{id}`

Edita nota. Permitido apenas em status RASCUNHO,
REPROVADO_GESTOR ou REPROVADO_DIRETOR. Apenas o criador.

Multipart/form-data, mesmos campos do POST (todos opcionais),
mais `new_files` para adicionar anexos.

### `DELETE /api/invoices/{id}`

Apaga nota. Só em status RASCUNHO. Apenas o criador.

### `POST /api/invoices/{id}/submit`

Envia nota para aprovação (RASCUNHO → AGUARDANDO_GESTOR ou
AGUARDANDO_DIRETOR).

**Query params**:
- `director_id`: se usuário tem `submit_directly_to_director`
- `confirm_duplicate`: bool — passa true para forçar mesmo após 409

**Erro 409 com `code=DUPLICATE_INVOICE_NUMBER`**:
```json
{
  "detail": {
    "code": "DUPLICATE_INVOICE_NUMBER",
    "message": "Já existe uma nota com o número 'NF-0001' ...",
    "existing_invoice_id": "uuid",
    "existing_status": "APROVADO"
  }
}
```

### `POST /api/invoices/{id}/cancel`

Cancela nota (volta para RASCUNHO). Disponível em estados não
finalizados.

### `POST /api/invoices/{id}/manager-review`

Gestor aprova ou reprova.

**Body**:
```json
{
  "action": "APPROVE",        // ou "REJECT"
  "comment": "motivo (obrigatório se REJECT)",
  "director_id": "uuid"       // obrigatório se APPROVE (escolhe destino)
}
```

### `POST /api/invoices/{id}/director-review`

Diretor aprova ou reprova.

**Body**:
```json
{
  "action": "APPROVE",
  "comment": "motivo (obrigatório se REJECT)"
}
```

### `POST /api/invoices/{id}/transfer-director`

Diretor atual transfere para outro diretor.

**Body**:
```json
{
  "new_director_id": "uuid",
  "comment": "motivo (min 10 chars)"
}
```

### Comprovante e lançamento

### `GET /api/invoices/{id}/print`

Gera o comprovante em PDF.

- **Sem efeito colateral** (idempotente — pode ser chamado N vezes)
- Útil para reimpressão de notas já PAGAS
- Permissões: ADMIN, FINANCE, CONTAS_A_PAGAR (este último só
  para notas PAGAS)
- Resposta: stream `application/pdf`

### `POST /api/invoices/{id}/mark-paid`

Lança a nota (APROVADO → PAGO) **e** devolve o comprovante.

- Acão explícita, idempotente (se já está PAGO, devolve PDF sem
  alterar)
- Apenas ADMIN e FINANCE
- Frontend chama com `confirmAction()` antes

### Anexos

### `GET /api/invoices/{id}/attachment`

Lista anexos da nota.

### `GET /api/invoices/{id}/attachment/{attachment_id}`

Baixa um anexo específico (decriptado on-the-fly).

### `DELETE /api/invoices/{id}/attachment/{attachment_id}`

Remove anexo. Apenas em estados editáveis. Pelo menos 1 anexo
precisa restar.

### `GET /api/invoices/{id}/all-attachments-merged`

Devolve PDF único com **todos os anexos** mesclados em ordem.
Útil para gestor/diretor ver tudo em uma janela.

### Comentários

### `GET /api/invoices/{id}/comments`

Thread paginada.

**Query**:
- `page`: int, default 1
- `per_page`: int, default 50, máx 200

**Resposta 200**:
```json
{
  "items": [
    {
      "id": "...",
      "body": "comentário",
      "created_at": "2026-06-03T20:00:00",
      "user": { "id": "...", "name": "Maria", "role": "MANAGER" }
    }
  ],
  "page": 1,
  "per_page": 50,
  "total": 7,
  "has_next": false
}
```

### `POST /api/invoices/{id}/comments`

Adiciona comentário (máx 2000 chars).

**Body**: `{"body": "texto"}`

### Verify público

### `GET /verify/{invoice_id}`

Página HTML pública com dados mascarados. Não exige login.

### `GET /api/invoices/{invoice_id}/verify-full`

API autenticada que devolve os dados completos. Chamada pelo
JavaScript da página verify quando detecta sessão ativa.

Apenas para usuários com acesso à nota
(criador, manager, director, finance, admin, contas_a_pagar).
Quem não tem acesso recebe **404 indistinguível** de nota
inexistente (evita oráculo de existência de UUID).

### Lookup CNPJ

### `GET /api/invoices/lookup-cnpj/{cnpj}`

Consulta dados de CNPJ na API externa (opencnpj.org) com cache
local de 180 dias.

Rate-limit: 30 requests em 60s por cliente.

---

## Admin

Endpoints abaixo exigem role ADMIN.

### Usuários

- `GET /api/admin/users` — lista todos
- `GET /api/admin/users/{id}` — detalhe
- `POST /api/admin/users` — cria (pode entrar em
  pending_admin_actions se for ADMIN ou DIRECTOR)
- `PATCH /api/admin/users/{id}` — edita
- `POST /api/admin/users/{id}/reset-password` — reset
  manual (força nova senha temporária)
- `POST /api/admin/users/{id}/close` — encerra (anonimiza)

### Setores

- `GET /api/admin/departments`
- `POST /api/admin/departments`
- `PATCH /api/admin/departments/{id}`
- `POST /api/admin/departments/{id}/assign-director`

### Audit log

- `GET /api/admin/audit-logs` — paginado, com filtros
- `GET /api/admin/audit-logs/verify-chain` — valida hash chain
  inteira

### Pending actions

- `GET /api/pending-actions/me` — ações pendentes que **outro**
  admin/diretor iniciou e que eu posso vetar
- `POST /api/pending-actions/{id}/veto` — veta com motivo

---

## Health checks

### `GET /health` (legado) / `GET /health/live`

Liveness probe. Sempre 200 com `{"status": "ok"}`. Não toca DB.

### `GET /health/ready`

Readiness probe. Checa banco com SELECT 1.

- 200 se DB OK
- 503 se DB falhou

### `GET /health/dependencies`

Estado detalhado de dependências externas (DB, R2, email).

---

## Headers de resposta importantes

- `X-Request-ID`: id único da request, ecoado se o cliente enviou
- `Retry-After`: segundos restantes na janela quando responde 429
- `X-RateLimit-Limit`, `X-RateLimit-Window`: na resposta 429
- `Set-Cookie: refresh_token=...` no login bem-sucedido
- `Set-Cookie: refresh_token="" ... Max-Age=0` em falhas do
  `/auth/refresh` (limpa cookie inválido)

---

## Códigos HTTP usados

- **200**: sucesso
- **201**: recurso criado
- **400**: erro de regra de negócio com mensagem clara
- **401**: não autenticado, sessão expirada
- **403**: autenticado mas sem permissão
- **404**: recurso não encontrado (ou existe e sem permissão, no
  caso do verify-full)
- **409**: conflito (duplicate detection)
- **422**: erro de validação Pydantic (formato `[{loc, msg, type}]`)
- **428**: precondition required (precisa trocar senha antes)
- **429**: rate-limit
- **503**: app não está pronto (config inválida ou DB caiu)
