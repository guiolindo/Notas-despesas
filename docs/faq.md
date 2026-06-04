# Perguntas técnicas frequentes

Soluções rápidas para problemas comuns. Para problemas operacionais
detalhados ver [operations.md](operations.md).

---

## Setup

### Por que o sistema não aceita meu Python 3.10?

O projeto exige Python 3.12 ou superior. Versões anteriores não
têm sintaxe `str | None` em alguns lugares e libs como o Pydantic 2.x
podem se comportar diferente.

### Como gerar uma chave Fernet válida?

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Saída exemplo: `Z8d4j8m_K3l9p2... =` (44 caracteres, base64).

### Como gerar um SECRET_KEY hex?

```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

Saída: 128 caracteres hexadecimais. O mínimo aceito pelo
fail-fast é 32 chars, mas usar 128 para folga.

### O sistema cria um admin padrão. Como mudar a senha?

Login com `admin@economart.com` / `Admin@2024!`. O sistema **obriga**
a troca de senha no primeiro login (flag `must_change_password=true`).

Para resetar a senha manualmente sem outro admin ativo, ver
[operations.md → reset de senha do admin](operations.md#reset-de-senha-do-admin).

---

## Sessão e login

### Por que sou desconectado a cada hora?

O **access token** dura 60 minutos. Quando expira, o frontend chama
`/auth/refresh` automaticamente usando o **cookie HttpOnly de
refresh** (que dura 7 dias). Você não deveria perceber.

Se está sendo desconectado de verdade após 1h:

- Cookie de refresh foi rejeitado. Possíveis causas:
  - Você trocou a senha há pouco (sessão antiga foi invalidada)
  - Sua conta foi desativada por um admin
  - Cookies third-party bloqueados no navegador
  - Você está usando o sistema em domínios diferentes
    (cookie SameSite=Strict)

### Por que estou bloqueado de logar?

Bloqueio temporário após **5 tentativas erradas seguidas**. Espere
10 minutos e tente de novo. Login bem-sucedido zera o contador.

Um email é enviado para a sua conta quando o bloqueio é aplicado —
serve para você saber se alguém está tentando entrar.

### Esqueci minha senha. Como recupero?

1. Em `/login`, clicar em "Esqueci minha senha"
2. Informar seu email
3. Você recebe um código de 6 dígitos por email
4. Em `/reset-password`, informar email + código + nova senha

Validade do código: 10 minutos. Tentativas máximas: 5.
Após sucesso, o código é invalidado. Códigos novos invalidam
os anteriores.

### Por que recebo 428 ao chamar a API?

`HTTP 428 Precondition Required` significa "você precisa trocar a
senha antes de fazer qualquer ação". Usuários criados pelo admin
ou após reset nascem com essa flag.

O frontend redireciona automaticamente. Cliente direto (curl,
integração) precisa primeiro chamar `POST /auth/change-password`.

---

## Notas e fluxo

### Por que não consigo enviar a nota?

Razões comuns:

- **Vencimento no passado**: notas com `due_date` anterior a hoje
  não podem ser enviadas. Atualizar a data primeiro
- **Sem alteração após reprovação**: nota reprovada exige que a
  descrição seja editada antes do reenvio. Mesmo conteúdo →
  bloqueio (anti-reenvio vazio)
- **Sem anexos**: pelo menos 1 PDF é obrigatório
- **Gestor indisponível sem substituto**: erro claro na resposta
- **Duplicate detection (HTTP 409)**: existe outra nota ativa com
  mesmo `invoice_number` + mesmo fornecedor (ou mesmo criador).
  Reenviar com `confirm_duplicate=true` se realmente é nota
  diferente

### O que é "envio direto pro diretor"?

Funcionários com flag `submit_directly_to_director=true` (configurada
pelo admin) podem pular o gestor e escolher diretamente um diretor.
Usado para níveis hierárquicos altos onde o "gestor" não faz sentido.

### Por que minha nota não aparece na fila do gestor?

Verificar (em ordem):

1. Status da nota é `AGUARDANDO_GESTOR`?
2. `manager_id` da nota aponta para o gestor correto?
3. O gestor está ativo (`users.is_active=true`)?
4. O gestor ainda tem role MANAGER (não foi promovido a DIRECTOR)?

### Por que não consigo aprovar/reprovar?

- Apenas o gestor designado na nota pode revisar
- Status precisa ser o esperado (gestor revisa em
  `AGUARDANDO_GESTOR`, diretor em `AGUARDANDO_DIRETOR`)
- Reprovar exige comentário (motivo) com 10+ caracteres
- Aprovar como gestor exige escolher um diretor de destino

### O que acontece com a nota reprovada?

Volta para o criador com status `REPROVADO_GESTOR` ou
`REPROVADO_DIRETOR`. O criador edita a descrição (obrigatório) e
reenvia.

Notas reprovadas **não tocadas em 90 dias** são automaticamente
apagadas (junto com seus anexos no R2). Limpeza para evitar lixo
acumulado.

### Como funciona o "imprimir e lançar"?

`POST /api/invoices/{id}/mark-paid` faz duas coisas atomicamente:

1. Transição APROVADO → PAGO (com auditoria)
2. Gera o PDF do comprovante e devolve

A separação de `GET /print` (preview/reimpressão, idempotente) e
`POST /mark-paid` (lançamento explícito) foi feita justamente
para evitar lançar pagamento por engano em reload da URL.

---

## PDFs e anexos

### Por que meu PDF não foi aceito?

- Tamanho > 10MB
- Total da nota > 25MB
- Arquivo não é PDF válido (corrompido, ou outro formato com
  extensão `.pdf`)
- PDF tem JavaScript embutido (bloqueado pelo `_check_pdf_safety`
  como medida anti-malware leve)
- Você já tem 5 anexos na nota (máximo)

### Onde os PDFs ficam guardados?

Criptografados (Fernet AES-256) no **Cloudflare R2**. O banco guarda
só a chave Fernet de cada arquivo, criptografada por sua vez com a
`MASTER_ENCRYPTION_KEY` da aplicação.

Vazamento do bucket → PDFs ilegíveis. Vazamento do banco → chaves
inúteis sem a `MASTER_ENCRYPTION_KEY`.

### Posso recuperar um PDF deletado?

Não pelo sistema. O R2 não tem versioning habilitado (roadmap).

Se acabou de deletar e tem backup do bucket, restaurar manualmente
fica como procedimento de operações.

### Como funciona o comprovante final?

`GET /api/invoices/{id}/print` gera um PDF com:

- Capa com dados da nota, valor formatado em PT-BR
- Carimbo de "Aprovado" / "Lançado"
- QR Code apontando para `/verify/{id}` (verificação externa)
- Trilha de aprovação (timeline: criação → gestor → diretor → lançamento)
- **Concatenação de todos os PDFs anexados**

Tudo em memória, sem tocar disco. O comprovante final pode ser
re-gerado a qualquer momento (não fica salvo).

---

## Verify público e LGPD

### O que o público vê em /verify?

Dados **mascarados**:

- Nome do criador, gestor, diretor: "João S****"
- Email: "joao.s****@economart.com.br"
- CPF/CNPJ: "***.456.789-**"
- Número da nota, valor, status, datas (não mascarados)

### Como funciona a revelação automática?

O JavaScript da página verify (`/static/js/verify.js`) detecta se
tem sessão válida via `window.Auth.hasSessionHint()`. Se tem,
chama `/api/invoices/{id}/verify-full` (endpoint autenticado).

Se você tem acesso à nota (criador, gestor, diretor, financeiro,
admin, contas a pagar), a página é reescrita com dados completos
**sem flash** — não tem "primeiro mostra mascarado, depois revela".

Se você não tem acesso, recebe HTTP 404 (indistinguível de nota
inexistente) e continua vendo o mascarado.

### Posso compartilhar o link de verify externamente?

Sim. É a função do QR Code do comprovante. Fornecedor, auditor
externo, fiscalização — todos podem validar a nota sem login.

Os dados que aparecem para anônimos foram desenhados para
**provar autenticidade** sem **vazar informação sensível**.

---

## Performance

### Listagem de notas está lenta. O que faço?

1. Usar `?fields=light` na chamada GET (desabilita eager loading
   de anexos e histórico)
2. Reduzir `per_page` (50 ou menos)
3. Aplicar filtros para reduzir o resultset (status, faixa de
   datas)
4. Em produção, verificar índices: `SELECT * FROM pg_indexes
   WHERE tablename='invoices'`

### O `/health/ready` está demorando

Esse endpoint faz `SELECT 1`. Se está lento, o problema é o banco
(conexão saturada, lock contention, etc), não o app.

### Cold start no Railway

Hobby tier pode ter cold start de 3-8s. O sistema mitiga com
**pre-warm do /refresh**: o `app.js` dispara `/auth/refresh` no
top-level (antes do DOMContentLoaded). Quando o usuário clica
em algo, o token já chegou.

Se está perceptivelmente lento mesmo assim, considerar upgrade
do plano Railway.

---

## Email

### Email não está chegando

Ver [operations.md → email não chega](operations.md#email-não-chega).

Resumo: checar `email_queue` no banco, ver se está PENDING/FAILED
e qual o `last_error`.

### Mudei o SMTP mas não pega

A configuração SMTP é via **variável de ambiente** apenas (não há
admin UI). Mudar no painel do Railway e **restart** o pod.

Se você está mexendo no admin UI tentando achar configuração SMTP,
ela não existe — decisão deliberada de segurança.

### Resend vs SMTP, qual escolher?

- **Resend**: HTTP API, funciona em Railway Hobby, 3000 emails/mês
  grátis, recomendado para começar
- **SMTP**: necessário se sua empresa já tem servidor próprio.
  Railway Hobby bloqueia SMTP de saída em muitos provedores
  como anti-spam

---

## Erros HTTP

### Por que recebo 404 em um endpoint que existe?

- URL errada (digitação)
- Verify-full + nota que não existe **ou** nota que existe mas
  você não tem acesso (404 indistinguível por design)
- Página HTML que existe mas você não está logado (redirect
  para /login)

### Por que recebo 422?

Erro de validação Pydantic. O body da request não tem o formato
esperado.

Formato da resposta:

```json
{
  "detail": [
    { "loc": ["body", "field"], "msg": "Field required", "type": "missing" }
  ]
}
```

`loc` indica qual campo está com problema, `msg` descreve.

### Por que recebo 428?

Sua conta tem `must_change_password=true`. Vá trocar a senha
em `/change-password` (ou `POST /auth/change-password` se for
cliente direto).

### Por que recebo 429?

Rate-limit atingido. Cabeçalho `Retry-After` indica em quantos
segundos você pode tentar de novo.

Limites:

| Endpoint | Limite | Janela |
|---|---|---|
| `/auth/login` | 10 | 60s |
| `/auth/forgot-password` | 5 | 600s |
| `/auth/reset-password` | 8 | 600s |
| `/api/invoices/lookup-cnpj/*` | 30 | 60s |
| `/api/invoices/*/comments` | 30 | 60s |

### Por que recebo 503?

Tela "Configuração de segurança incompleta". `SECRET_KEY` ou
`MASTER_ENCRYPTION_KEY` estão vazias/inseguras em PROD. Operador
precisa configurar no Railway.

---

## Banco de dados

### Estou usando SQLite em produção e quebrou

Você não deveria. SQLite é só para desenvolvimento local. Em
produção use Postgres (via `DATABASE_URL=postgresql://...`).

### Como conectar no Postgres do Railway?

Painel Railway → Postgres plugin → Connect → Connection String.
Copiar e usar com `psql`:

```bash
psql 'postgresql://user:pass@host:port/dbname'
```

### As migrações são confusas. Como sei o que rodou?

`app/main.py:_run_schema_migrations` lista todas em ordem. Cada
uma é `ALTER TABLE ... IF NOT EXISTS` ou `ALTER TYPE ...`. O
sistema roda todas no boot, ignora silenciosamente erros (já
aplicado ou não suportado em SQLite).

Para checar o estado atual de uma tabela:

```sql
\d+ invoices              -- PG: schema completo
PRAGMA table_info(invoices); -- SQLite
```

---

## Desenvolvimento

### Como adiciono uma migration?

Editar `app/main.py:_run_schema_migrations` e adicionar a linha
`pg("ALTER TABLE ... IF NOT EXISTS ...")` ou
`sqlite("...")` conforme o dialeto.

Atenção: migrations são **forward-only**. Sem rollback automático.
`ALTER TYPE ADD VALUE` em PG é irreversível.

### Como adiciono um endpoint?

1. Router em `app/routers/<área>.py` com `@router.get(...)` etc
2. Schema em `app/schemas/` se receber JSON estruturado
3. Service em `app/services/` se a lógica é não-trivial
4. Teste em `tests/test_<área>.py`

Ver `docs/api-reference.md` para padrões.

### Como adiciono uma página HTML?

Ver [frontend.md → como contribuir](frontend.md#como-contribuir).

### Os logs estão poluídos. Como filtro?

Tudo tem `[req=<id>]`. Para isolar uma request:

```bash
railway logs | grep "req=abc123def456"
```

O ID vem no header `X-Request-ID` da resposta — peça ao usuário
do incidente.

---

## Roadmap (perguntado com frequência)

### Por que não tem Alembic?

Migrations manuais no startup são suficientes para a escala
atual. Adicionar Alembic implica nova infra (revisões, lockfile,
template) e procedimento de deploy. Roadmap quando o time crescer.

### Por que não tem Sentry?

Logs do Railway cobrem hoje. Roadmap quando crescer ou houver
incidentes que pedem correlação centralizada.

### Por que não tem backup off-site?

Postgres do Railway tem backup automático no plano. Off-site
adicional implica orçamento + procedimento de rotação. Roadmap.

### Por que app.js tem 3300 linhas?

Tentamos splitar uma vez e causou regressão (botões "morrendo").
Revertemos. Plano de split está em `_audit-internal/` (cache local
da auditoria), e refazer com smoke test runtime obrigatório está
no roadmap.
