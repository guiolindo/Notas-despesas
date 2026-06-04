# Testes — suite automatizada e estratégia

Este documento descreve a suite de testes automatizados, como
rodá-la e como adicionar novos testes.

## Estado atual

- **21 testes pytest** verdes
- Cobrem regressões de **P0/P1** do trabalho de auditoria
- Tempo total: ~12 segundos
- Sem testes E2E de browser ainda
- Cobertura de código não medida (sem `coverage.py` instalado por padrão)

## Pré-requisitos

```bash
pip install pytest
```

`pytest` é dependência de **dev**, não está no `requirements.txt`
principal porque produção não precisa. Para CI ou setup de
desenvolvimento, instalar separadamente.

## Como rodar

```bash
# Suite completa
python -m pytest tests/ -q

# Verbose (mostra cada teste)
python -m pytest tests/ -v

# Um arquivo específico
python -m pytest tests/test_auth_security.py

# Um teste específico
python -m pytest tests/test_auth_security.py::test_login_and_refresh_cycle

# Parar no primeiro erro
python -m pytest tests/ -x

# Mostrar print() dos testes
python -m pytest tests/ -s
```

Saída esperada (suite verde):

```
============================= test session starts =============================
collected 21 items

tests/test_auth_security.py .....
tests/test_business_rules.py ....
tests/test_email_queue.py ...
tests/test_health.py .....
tests/test_rate_limit.py ...

21 passed, 3 warnings in 11.94s
```

(Os 3 warnings são deprecation do Pydantic e FastAPI sobre
`@app.on_event` — não afetam os testes.)

---

## Estrutura

```
tests/
├── __init__.py
├── conftest.py                  # fixtures compartilhadas
├── test_health.py               # P1-7
├── test_auth_security.py        # P0-1, P1-6, P1-8
├── test_rate_limit.py           # P1-5
├── test_email_queue.py          # P2-8
└── test_business_rules.py       # P1-3, P1-9
```

### conftest.py

Define fixtures usadas em vários arquivos:

- **`_test_env`** (session-scoped): cria um diretório temporário, gera
  `SECRET_KEY` e `MASTER_ENCRYPTION_KEY` aleatórios, aponta
  `DATABASE_URL` para um SQLite isolado. Todas as variáveis de
  ambiente são setadas **antes** de qualquer `import app.main`
- **`app`**: importa `app.main:app` depois do `_test_env`. Lazy
  import garante que os settings já estão corretos
- **`client`** (function-scoped): cria um `TestClient` novo para
  cada teste. Cada teste recebe instância fresca para evitar
  vazamento de cookies entre cenários

O SQLite é o **mesmo arquivo** durante toda a sessão pytest. Testes
devem ser idempotentes ou criar dados isolados (UUIDs únicos).

---

## O que cada arquivo cobre

### `test_health.py` (5 testes)

- `test_health_live_responds_ok`: liveness simples
- `test_health_ready_checks_db`: readiness com SELECT 1
- `test_request_id_middleware_echoes`: header X-Request-ID é
  ecoado quando o cliente envia
- `test_request_id_middleware_generates_when_absent`: server
  gera ID quando cliente não envia
- `test_request_id_sanitizes_garbage`: input malicioso
  (`drop tables; --`) é rejeitado e substituído

### `test_auth_security.py` (5 testes)

- `test_refresh_without_cookie_returns_401`: 401 sem oráculo
- `test_refresh_with_invalid_cookie_returns_401_and_clears_cookie`:
  cookie quebrado → 401 + Set-Cookie de remoção (P0-1)
- `test_login_and_refresh_cycle`: fluxo feliz completo
- `test_change_password_invalidates_old_refresh`: refresh
  emitido antes da troca de senha falha (P0-1, core do achado)
- `test_must_change_password_blocks_api_with_428`: backend
  bloqueia API quando flag está True (P1-8)
- `test_verify_full_returns_404_for_missing_or_forbidden`:
  ambos retornam 404 indistinguível (P1-6)

### `test_rate_limit.py` (3 testes)

- `test_login_rate_limit_blocks_after_threshold`: 11ª tentativa
  → 429 com Retry-After
- `test_forgot_password_rate_limit`: 6ª tentativa de
  forgot-password → 429
- `test_health_not_rate_limited`: 30 chamadas seguidas a
  `/health/live` continuam 200 (não pode ter rate-limit)

### `test_email_queue.py` (3 testes)

- `test_enqueue_creates_pending_row`: enqueue cria row com
  status PENDING e attempts=0
- `test_drain_marks_failed_after_max_attempts`: provedor
  sempre falha → row vira FAILED após max_attempts
- `test_drain_marks_sent_on_success`: provedor sucesso →
  status=SENT, sent_at preenchido

### `test_business_rules.py` (4 testes)

- `test_p1_9_manager_unavailable_blocks_submit`: gestor em
  férias sem substituto bloqueia submit com mensagem clara (P1-9)
- `test_p1_9_manager_unavailable_with_substitute_routes_to_substitute`:
  com substituto válido, nota vai direto pro substituto
- `test_p1_3_duplicate_invoice_number_blocked_without_confirm`:
  409 com code DUPLICATE_INVOICE_NUMBER (P1-3)
- `test_p1_3_duplicate_allowed_with_confirm_duplicate`: passando
  `confirm_duplicate=true` contorna o block

---

## Padrões dos testes

### Helpers compartilhados

`test_business_rules.py` define helpers reutilizáveis:

```python
_make_user(role, manager_id, **extra)
_login(client, email, password)
_invoice_payload(invoice_number, supplier_doc)
_create_invoice(client, headers, payload)
```

Quem adiciona testes novos pode reusar.

### Email TLD

Usar `@example.com` ou `@economart.local.example.com` para emails
de teste. Pydantic rejeita `@test` e `@local` como TLDs reservados.

### Form-data vs JSON

`POST /api/invoices/` usa multipart/form-data (por causa dos
anexos). Testes precisam mandar via `client.post(url, data=...)`
não `json=...`. Helper `_create_invoice` já cuida.

### Timestamp e tolerância

`token_is_pre_password_change` tem tolerância de 2 segundos.
Para testar invalidação de refresh, force `password_changed_at` no
futuro:

```python
user.password_changed_at = datetime.now(timezone.utc) + timedelta(minutes=5)
```

### Monkeypatch para provedores externos

Testes não devem mandar email de verdade. `test_email_queue.py`
monkeypatcha o `_try_send` do worker:

```python
monkeypatch.setattr(eqs, "_try_send", lambda row: (True, None))
```

---

## Como adicionar um teste novo

1. Criar arquivo `tests/test_<area>.py` se a área não existe
2. Escrever função `test_<descrição>(client, ...)`:
   ```python
   def test_minha_regra(client):
       """Descrição curta da regra de negócio."""
       email, password, _ = _create_active_user(client.app)
       headers = _login(client, email, password)
       resp = client.get("/api/...", headers=headers)
       assert resp.status_code == 200
       assert resp.json() == {...}
   ```
3. Rodar: `python -m pytest tests/test_<area>.py -v`
4. Se passar, rodar a suite toda para garantir que não quebrou
   outros testes

### Fixture diferente?

Se precisa de fixture nova compartilhada, adicionar em `conftest.py`.
Documentar bem para outros desenvolvedores.

---

## Bugs descobertos pela suite

A suite não foi só "checklist". Encontrou bugs reais durante a
implementação:

1. **`/auth/refresh` não apagava cookie em falhas.**
   `response.delete_cookie()` antes de `raise HTTPException` não
   funciona — FastAPI gera nova resposta a partir da exceção.
   Solução: helper `_refresh_unauthorized()` injeta Set-Cookie
   no header da própria HTTPException.

2. **`token_is_pre_password_change` com falso positivo de até 1s.**
   JWT `iat` em segundos vs `password_changed_at` em microsegundos.
   Login imediato após troca podia disparar logout em loop.
   Solução: tolerância de 2 segundos.

Esses bugs estavam em produção mas escaparam de revisão visual.
Sem a suite, continuariam ali.

---

## O que falta cobrir (roadmap)

- **Fluxo financeiro end-to-end**: criar → submit → aprovar gestor →
  aprovar diretor → mark-paid. Hoje cobre só partes
- **Upload de PDF**: validar bloqueio de PDFs com JavaScript
  embutido, tamanho máximo, máximo de anexos
- **Hash chain de audit**: verify-chain detecta tampering
- **Anonimização (encerramento de usuário)**: garantir que
  audit_logs e approval_history sobrevivem
- **Substitute de diretor**: análogo ao manager mas para directors
- **Comentários**: paginação, limite de 2000 chars
- **Verify público**: máscara LGPD, revelação por login
- **Page guards**: redirect para /login, 403 para role errada

---

## Integração contínua (CI)

Não há GitHub Actions configurado ainda. Roadmap.

Quando configurar, sugestão de workflow:

```yaml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt pytest
      - run: python -m pytest tests/ -v
```

---

## Smoke test manual (complemento da suite)

Antes de deploy não-trivial em PROD, rodar manualmente:

1. Login como admin default → trocar senha
2. Criar setor "Teste"
3. Criar usuário gestor neste setor
4. Criar usuário funcionário com este gestor
5. Login funcionário → criar nota com PDF anexo → enviar
6. Login gestor → ver nota na fila → aprovar
7. Login admin (que também tem permissão de diretor neste cenário)
   → aprovar
8. Login finance (ou usar admin) → lançar
9. Abrir `/verify/{id}` em aba anônima → verificar mascaramento
10. Logar na mesma aba → verificar revelação

Cobre o caminho feliz completo + permissões.
