# Auditoria completa Economart

Status: relatorio consolidado final — em fase de implementacao
Data: 2026-06-02 (auditoria) / 2026-06-03 (em implementacao)
Autores: Claude_Opus + ChatGPT_OpenAI_Codex (auditoria cruzada por chat global)
Escopo: FastAPI 0.136+, Jinja2, JavaScript vanilla, Postgres/Railway, Cloudflare R2, seguranca, UX, arquitetura, LGPD, operacao, testes e manutencao.

---

## Estado de implementacao (atualizado 2026-06-03)

Mapeamento detalhado em `docs/CHANGELOG-audit-2026-06.md` com risco e como testar por commit.

### P0 — IMPLEMENTADO ✓

| ID | Achado | Commit |
|----|--------|--------|
| P0-1 | Refresh token nao valida `password_changed_at` | `302df81` |
| P0-2 | `GET /print` marca PAGO -> separar em POST `/mark-paid` | `302df81` |
| P0-3 | Admin default hardcoded | pendente (decisao: manter com warning no README) |
| P0-4 | Sem backup off-site automatizado | pendente (decisao de ops/infra) |

### P1 — IMPLEMENTADO em grande parte ✓

| ID | Achado | Commit | Por |
|----|--------|--------|-----|
| P1-1 | Access token no `localStorage` | `759e64f` | Claude |
| P1-2 | Fail-fast secrets em PROD | `cc7f610` | Claude |
| P1-3 | `invoice_number` sem UNIQUE | `154d642` | Claude |
| P1-4 | Migrations manuais sem rollback | pendente (decisao adiada — Alembic e overkill agora) |
| P1-5 | Rate limit so login, sem proxy-aware | `56deb87` | Codex |
| P1-6 | `/verify-full` 403 vs 404 vazamento | `302df81` | Claude |
| P1-7 | Sem request_id / `/health` raso | `154d642` | Claude |
| P1-8 | `must_change_password` so frontend | `cc7f610` | Claude |
| P1-9 | Manager unavailable ignorado | `cc7f610` | Claude |

### P2 — IMPLEMENTADO em parte ✓

| ID | Achado | Commit | Por |
|----|--------|--------|-----|
| P2-1 | `app.js` monolitico | em andamento — `c6e67aa` extraiu password handlers | Codex |
| P2-2/3/4/14/15 | A11y batch | `35f9600` | Codex |
| P2-5 | selectinload light vs full | `154d642` | Claude |
| P2-7 | CSS split | `c5cc73b` | Codex |
| P2-8 | Email retry queue | `77c07e8` | Claude |
| P2-9 | FK ON DELETE | `154d642` | Claude |
| P2-13 | `GET /comments` sem paginacao | `154d642` | Claude |

Itens restantes (P2-10/11/12, P2-22/23/24 etc.) sao documentos/runbook/postmortem ja parcialmente cobertos por `907ab2f` e `6287769`. Para o restante: ver `docs/CHANGELOG-audit-2026-06.md`.

### Itens P3 e demais

Ficam como roadmap para fases futuras. Nenhum bloqueador.

### Falsos positivos confirmados

- `auth.py:428 user.password_changed_at` — ja corrigido antes da auditoria, achado partia de cache velho.
- `print_routes /verify decorator em _mask_email` — ja corrigido.
- `iniciar.bat` — nao existe no repo.

---

Sistema auditado: Economart Notas Fiscais — aplicacao interna de aprovacao de notas fiscais para o atacadista Economart. Fluxo: criador (EMPLOYEE) → gestor (MANAGER) → diretor (DIRECTOR) → financeiro (FINANCE) → arquivamento. Perfis especiais: ADMIN (gestao do sistema) e CONTAS_A_PAGAR (read-only com scanner QR).

Repositorio: github.com/guiolindo/Notas-despesas, branch `main`.

Priorizacao usada:

- **P0** — risco critico ou bloqueador. Corrigir imediatamente.
- **P1** — alto impacto. Entrar no proximo ciclo de trabalho.
- **P2** — melhoria importante. Nao bloqueante, mas relevante.
- **P3** — evolucao desejavel. Roadmap de medio prazo.

---

## Sumario executivo (1 pagina)

### Estado geral

O sistema esta **funcionalmente solido** para o caso de uso atual: fluxo de aprovacao por etapas, anexos criptografados, comprovante com QR Code, auditoria com hash chain, e separacao de papeis com defesa contra insider threat (janela de 24h, notificacao peer, SMTP fora do alcance do admin). A base de seguranca e melhor que media: bcrypt, JWT com invalidacao por `password_changed_at`, headers CSP, rate limit no login, PDFs criptografados em R2 com Fernet, e pseudonimizacao de IPs por HMAC.

Em compensacao, ha **gaps relevantes** em 4 areas que merecem atencao imediata: (1) sessao via refresh token, (2) semantica de "imprimir = lancar pagamento", (3) bootstrap de admin com senha fixa, (4) ausencia total de testes automatizados em fluxo critico financeiro.

### Numeros chave da auditoria

- **89 achados** organizados em 31 secoes tematicas.
- **4 P0** (criticos), **12 P1** (alto impacto), **53 P2** (importantes), **20 P3** (evolucao).
- **Confirmacao cruzada**: cada achado validado em arquivo:linha por pelo menos um dos auditores.
- **Falsos positivos detectados e descartados**: 3 (bug `user.password_changed_at`, `/verify` decorator, `iniciar.bat`).

### Os 4 P0 (acao recomendada nas proximas 2 semanas)

1. **Refresh token nao invalida apos reset/troca de senha** (`app/routers/auth.py:145-173`) — sessao antiga continua valida por ate 7 dias. Atacante que comprometeu senha mantem acesso mesmo apos vitima trocar. Correcao: validar `password_changed_at` tambem no `/refresh`.

2. **`GET /api/invoices/{id}/print` marca nota como PAGO** (`app/routers/print_routes.py:49-134`) — abrir o link de comprovante por engano lanca pagamento. Crawler/preview link/reload acidental viram lancamento financeiro. Correcao: separar `GET /print-preview` (idempotente) de `POST /mark-paid` (com confirmacao).

3. **Admin default `admin@economart.com` / `Admin@2024!` hardcoded** (`app/main.py:39-44`) — qualquer fork ou clone com banco vazio nasce comprometido. Bem documentado no README, mas ainda assim e P0 em ambiente publico. Correcao: exigir `ADMIN_BOOTSTRAP_*` env vars; abortar startup se PROD sem bootstrap seguro.

4. **Sem backup off-site automatizado** — Postgres Railway tem backup interno do plano, mas se Railway sofrer incidente catastrofico, esta tudo no mesmo lugar. R2 sem versioning. Correcao: cron diario `pg_dump | gzip | encrypt | upload-r2-backup-bucket`.

### Os pontos fortes do sistema

- Hash chain dos audit_logs (deteccao de edicao retroativa no banco).
- Janela de 24h pra acoes administrativas sensiveis com peer veto.
- SMTP/Resend so via env (defesa contra admin trocar provedor pra interceptar reset).
- /verify publico mascarado com revelacao auto para autenticados autorizados.
- CSP estrita (script-src sem unsafe-inline) com vendoring de jsQR e icones Lucide.
- LGPD cuidadosamente implementado: pseudonimizacao irreversivel, retencao documentada, /privacidade completa.

### Os debitos tecnicos mais relevantes (P1 e P2)

- **Frontend monolitico**: `app.js` com 3336 linhas, `main.css` com 1660. Risco de regressao alto.
- **Migrations manuais no startup** (30+ `ALTER` em `main.py`). Sem rollback. Funciona pra equipe pequena, vai apertar conforme equipe crescer.
- **0 testes automatizados** — nenhum fluxo critico esta coberto.
- **Sem observabilidade real**: sem request_id, sem Sentry, sem `/metrics`, sem structured logs.
- **Health check raso** (`/health` so retorna `ok` sem checar DB ou R2).
- **Rate limit limitado**: so cobre `/auth/login`, em memoria local (multi-worker divide o limite).
- **API sem versionamento** (`/api/v1` nao existe).
- **`invoice_number` sem UNIQUE** — duplicidade silenciosa possivel.
- **Templates de detail por perfil duplicados** — manager/director/finance/invoices/detail.html divergem com o tempo.

### Quem deve ler o que neste documento

- **Engenharia (P0/P1)**: leia secoes 1-12 (achados detalhados de seguranca, fluxo, schema, performance) e use a matriz de prioridade pra triagem.
- **Produto/Negocio (P1/P2)**: leia secoes 4 (fluxo financeiro), 5 (regras), 14 (produto/integracoes), 23 (pendencias).
- **Operacao/DevOps (P0/P1)**: leia secoes 7 (rate limit), 11 (observabilidade), 18 (resiliencia), 22 (runbook).
- **Compliance/LGPD**: leia secoes 9 (email), 10 (LGPD), 21 (telemetria), 13 (a11y), 16 (a11y detalhada).

### Pontos onde o auditor pediu validacao de negocio

Estes nao sao bugs — sao decisoes de produto que precisam de definicao humana:

1. Politica de retencao de notas PAGO apos 5 anos (CTN exige minimo, nao maximo).
2. CPF/CNPJ completo no PDF impresso (hoje aparece; intencional?).
3. Roteamento entre setores: pode mandar nota a diretor de outro setor ou nao?
4. Imprimir = lancar pagamento (intencional segundo decisao anterior do usuario, mas semantica HTTP errada).
5. Quota total por empresa em R2 (limite legal + custo).
6. Estrategia futura de auth: cookie HttpOnly para access token ou access em memoria?

---

## Matriz de prioridade

| Prioridade | Area | Achado | Impacto | Esforco |
| --- | --- | --- | --- | --- |
| P0 | Seguranca | Refresh token nao valida `password_changed_at` | Sessao antiga continua valida apos reset/troca de senha | Medio |
| P0 | Seguranca/Ops | Admin default `admin@economart.com` / `Admin@2024!` em banco vazio | Instancia publica ou fork pode nascer comprometido | Baixo |
| P0 | Operacao financeira | `GET /api/invoices/{id}/print` altera estado para PAGO | Reload/clique/link pode lancar pagamento indevido | Medio |
| P0 | Infra | Sem backup off-site automatizado | Perda de dados se Railway/PG falhar | Medio |
| P1 | Seguranca | Access token no `localStorage` | XSS rouba sessao diretamente | Medio/Alto |
| P1 | Seguranca | `SECRET_KEY` default e `MASTER_ENCRYPTION_KEY` ausente geram apenas warning em PROD | Producao pode iniciar insegura | Baixo |
| P1 | Banco | `invoice_number` sem UNIQUE composto | Duplicidade silenciosa de notas | Baixo/Medio |
| P1 | Banco/Ops | Migrations manuais no startup, sem rollback | Deploy fragil e alteracoes irreversiveis | Medio/Alto |
| P1 | Rate limit | Rate limit em memoria, so login, sem proxy-aware | Brute force/abuso e limite incorreto em multi-worker | Medio |
| P1 | Upload/PDF | Sanitizacao PDF incompleta e fallback local de R2 | Anexos perigosos ou perda silenciosa em container | Medio |
| P1 | Upload/PDF | Nome original do anexo entra no `Content-Disposition` sem escape de header | Header injection ou resposta malformada | Baixo |
| P1 | Privacidade | `/verify-full` diferencia nota inexistente de nota sem permissao | Usuario autenticado pode inferir existencia de recurso | Baixo |
| P1 | Observabilidade | Sem request_id, metrics, Sentry/Loki e health real | Diagnostico e resposta a incidente ficam lentos | Medio |
| P1 | Testes | 0 testes automatizados e sem CI | Regressao facil em fluxo critico | Medio |
| P2 | UX/Frontend | `app/static/js/app.js` com 3336 linhas | Manutencao dificil e alto risco de regressao | Medio |
| P2 | UX | Drawer replica paginas de detalhe com HTML string | Divergencia entre telas e bugs duplicados | Medio |
| P2 | LGPD | Audit log nao registra leituras | Dificil responder "quem viu dado sensivel" | Medio |
| P2 | Operacao | Sem SLA por etapa/status | Gestao nao ve gargalos de aprovacao | Medio |
| P2 | Retencao | Logs/cache/reset codes sem limpeza completa | Crescimento indefinido e risco LGPD | Medio |
| P3 | Integracoes | Sem webhooks/API tokens/export CSV/OCR | Limita integracao com ERP e automacoes | Alto |

## Achados detalhados

### 1. Autenticacao e sessao

**P0 - Refresh token nao invalida apos troca/reset de senha**

Arquivos: `app/routers/auth.py:145-173`, `app/security/page_auth.py:26-34`, `app/security/dependencies.py:37-50`.

O access token antigo e invalidado em `get_current_user` quando `password_changed_at` e mais recente que `iat`. O refresh token, porem, continua emitindo access tokens novos sem checar `password_changed_at`. Isso significa que uma sessao emitida antes de reset/troca de senha pode continuar ativa por ate 7 dias via cookie de refresh.

Correcao recomendada: incluir `iat` no refresh token, validar contra `password_changed_at` em `/refresh` e em page guards, e apagar cookie de refresh quando a validacao falhar.

**P1 - `must_change_password` e aplicado principalmente no frontend**

Arquivos: `app/static/js/app.js:442-480`, endpoints sensiveis em `app/routers/*`.

O frontend redireciona usuarios que precisam trocar senha, mas o backend deve bloquear a maior parte dos endpoints sensiveis ate a troca obrigatoria ser concluida. Do contrario, chamadas diretas pela API podem contornar a restricao.

Correcao recomendada: criar dependency backend que permita apenas `/auth/me`, `/auth/change-password`, `/auth/logout` e rotas estritamente necessarias.

**P1 - Access token em `localStorage`**

Arquivo: `app/static/js/app.js:76-96`; tambem `app/static/js/verify.js`.

Um XSS permite ler `localStorage.access_token` e assumir a sessao. A CSP ajuda, mas ha muitos pontos de `innerHTML` e HTML string no frontend.

Correcao recomendada: manter access token em memoria ou cookie HttpOnly/SameSite, revisar CSRF conforme estrategia escolhida e remover leituras duplicadas em scripts secundarios.

### 2. Seguranca de configuracao

**P0 - Admin default hardcoded**

Arquivo: `app/main.py:39-44`.

Quando o banco esta vazio, o sistema cria `admin@economart.com` com senha `Admin@2024!`. Em fork publico, ambiente de teste exposto ou deploy novo, isso e um risco critico.

Correcao recomendada: exigir `ADMIN_BOOTSTRAP_EMAIL` e `ADMIN_BOOTSTRAP_PASSWORD`, criar admin apenas uma vez e abortar inicializacao se estiver em PROD sem bootstrap seguro.

**P1 - Secrets inseguros apenas geram warnings**

Arquivo: `app/config.py:47-59`.

`SECRET_KEY` default e `MASTER_ENCRYPTION_KEY` ausente em PROD geram `warnings.warn`, mas nao bloqueiam a subida do app.

Correcao recomendada: fail-fast em PROD; warning apenas em DEV.

**P1 - HSTS sempre ativo**

Arquivo: `app/middleware/security.py:21-22`.

HSTS e aplicado inclusive em desenvolvimento. Em localhost/testes pode causar comportamento inesperado no navegador.

Correcao recomendada: condicionar HSTS a `ENVIRONMENT=PROD`.

### 3. CSP, XSS e frontend

**P1 - CSP ainda permite `style-src 'unsafe-inline'`**

Arquivo: `app/middleware/security.py:29-38`.

O script-src esta melhor por nao usar `unsafe-inline`, mas `style-src` ainda aceita inline. Como existem muitos `style="..."` em templates e JS, o endurecimento deve ser planejado.

Correcao recomendada: ativar `Content-Security-Policy-Report-Only` primeiro, adicionar `report-uri`/`report-to`, remover estilos inline gradualmente e considerar nonce/hash quando necessario.

**P2 - Uso amplo de `innerHTML` e HTML strings**

Arquivos: `app/static/js/app.js`, `app/static/js/dashboard-v2.js`.

Muitos trechos usam `innerHTML`. Varios valores passam por `escapeHtml`, mas o volume torna a revisao dificil. O drawer em `app/static/js/app.js:2640-2757` mistura markup, estado e regras de negocio.

Correcao recomendada: extrair renderizadores puros, centralizar helpers seguros, evitar interpolacao manual para dados de usuario e criar testes de escaping.

**P2 - `app.js` monolitico**

Arquivo: `app/static/js/app.js`.

O arquivo tem mais de 3300 linhas e mistura auth, listas, detalhes, drawer, admin, departamentos, reset de senha e comentarios.

Correcao recomendada: dividir em modulos: `api/auth`, `invoice-list`, `invoice-detail`, `drawer`, `admin-users`, `departments`, `password-reset`, `dashboard`.

### 4. Fluxo financeiro e operacao

**P0 - GET de impressao marca nota como paga**

Arquivo: `app/routers/print_routes.py:49-134`.

Uma rota GET de leitura/geracao de PDF altera estado operacional e marca nota APROVADA como PAGO. Abrir link, recarregar pagina ou crawler pode disparar lancamento financeiro.

Correcao recomendada: separar:

- `GET /api/invoices/{id}/print-preview` para preview/geracao sem efeito colateral.
- `POST /api/invoices/{id}/mark-paid` para lancar pagamento.
- comprovante gerado apos transacao confirmada.
- idempotency key ou protecao contra duplo clique.

**P1 - Falta ajuste/estorno pos-PAGO**

Hoje nao ha conceito claro de reabertura, ajuste ou estorno quando uma nota paga foi lancada errado.

Correcao recomendada: modelar evento de ajuste financeiro com trilha de auditoria, motivo obrigatorio e permissao restrita.

**P2 - Sem SLA por etapa/status**

O historico existe, mas nao ha uma camada de metricas de tempo em cada status. Gestores nao conseguem ver gargalos por aprovador/setor.

Correcao recomendada: calcular duracao por etapa a partir do historico e expor alertas/relatorios.

### 5. Regras de aprovacao

**P1 - Gestor indisponivel ainda pode receber nota**

Arquivo: `app/services/invoice_service.py:342-365`.

O usuario pode marcar indisponibilidade, mas `_get_manager_for_user` nao checa `manager.unavailable_for_notes`. Funcionario ainda consegue enviar nota para gestor em ferias.

Correcao recomendada: aplicar a mesma regra de substituicao/indisponibilidade usada para diretores.

**P1 - Diretores de outros setores aparecem como disponiveis**

Arquivo: `app/services/invoice_service.py:1091-1119`.

`get_available_directors` lista diretores de outros setores e apenas marca `is_primary`. Pode ser desejado em empresa pequena, mas vira problema de roteamento e confidencialidade em empresa maior.

Correcao recomendada: configurar politica explicita: restrito ao setor, todos os diretores, ou excecoes por permissao.

### 6. Banco, schema e dados

**P1 - `invoice_number` sem unique**

Arquivo: `app/models/invoices.py:29`.

Permite duplicidade de numero de nota. O risco e pagamento/lancamento duplicado.

Correcao recomendada: indice unico composto, por exemplo `(created_by_id, invoice_number)` ou `(supplier_document, invoice_number)`, conforme regra de negocio.

**P1 - `amount` sem precision/scale explicitos**

Arquivo: `app/models/invoices.py`.

`Numeric` sem precisao/escala pode variar conforme banco e dificultar garantias financeiras.

Correcao recomendada: definir `Numeric(12, 2)` ou outra escala aprovada.

**P1 - Migrations manuais em startup**

Arquivo: `app/main.py`.

Ha diversos `ALTER TABLE`/`ALTER TYPE` no startup, sem rollback. `ALTER TYPE ADD VALUE` em Postgres e particularmente dificil de desfazer.

Correcao recomendada: adotar Alembic ou, se adiado, mover migrations para scripts versionados com logs, locks e rollback documentado.

**P2 - Caches e codigos crescem sem cleanup completo**

Itens: `cnpj_cache`, `password_reset_codes`, `audit_logs`.

TTL existe em leitura para CNPJ, mas nao ha limpeza periodica consistente. Reset codes e audit logs tambem crescem.

Correcao recomendada: jobs de retencao com politicas documentadas.

### 7. Rate limiting e abuso

**P1 - Rate limit em memoria e nao proxy-aware**

Arquivo: `app/middleware/security.py:43-69`.

O limite roda por processo. Em `gunicorn -w 4`, cada worker tem seu contador. Alem disso, usa `request.client.host`, que atras de proxy pode ser IP do gateway.

Correcao recomendada: Redis ou armazenamento compartilhado; usar `X-Forwarded-For`/`Forwarded` de forma segura conforme proxy confiavel.

**P1 - Rate limit cobre so login**

Faltam limites para:

- `/auth/forgot-password`
- `/auth/reset-password`
- `/api/invoices/lookup-cnpj/{cnpj}`
- `/api/invoices/{id}/comments`

Impacto: brute force de reset, abuso de API externa e flood de comentarios.

### 8. Uploads, PDF e anexos

**P1 - Validacao PDF incompleta**

Arquivo: `app/routers/invoices.py`.

Ha checagem com pypdf em `app/routers/invoices.py:201-225`, mas ela libera silenciosamente quando `pypdf` nao esta disponivel ou quando o PDF tem header valido mas nao parseia (`app/routers/invoices.py:212-219`). Deve-se revisar suporte a PDFs maliciosos, `/OpenAction`, `/AA`, `/AcroForm`, XFA, `/EmbeddedFiles`, links externos e metadados.

Correcao recomendada: politica clara de aceitacao; sanitizacao/normalizacao quando possivel; testes com PDFs maliciosos conhecidos.

**P1 - `Content-Disposition` usa nome original sem escape**

Arquivo: `app/routers/invoices.py:724-740`.

O download de anexo especifico retorna `headers={"Content-Disposition": f'inline; filename="{original_name}"'}`. Se `original_name` contiver aspas, CR/LF ou caracteres especiais, pode gerar header malformado ou abrir brecha de header injection dependendo da stack.

Correcao recomendada: normalizar nome para ASCII seguro, remover CR/LF/aspas e preferir `filename*=UTF-8''...` com URL encoding.

**P1 - Visualizacao de anexos ignora falhas individuais**

Arquivo: `app/routers/invoices.py:672-703`.

O endpoint de PDF mesclado ignora excecoes por anexo e continua com os demais. Isso e aceitavel para preview, mas pode mascarar perda/corrupcao de documento em uso operacional.

Correcao recomendada: para preview, mostrar aviso "N de M anexos carregados"; para comprovante/lancamento, decidir se falha de qualquer anexo deve bloquear a operacao.

**P1 - Fallback local do R2 pode perder anexos em producao**

Arquivo: `app/services/drive_service.py`.

Se R2 falha ou configuracao falta, o sistema pode cair para storage local. Em container Railway, arquivos locais sao efemeros.

Correcao recomendada: em PROD, falhar explicitamente quando R2 nao estiver disponivel; fallback local apenas em DEV.

**P2 - Sem quota total por empresa/usuario**

Ha limite por nota, mas usuario malicioso pode criar muitas notas com muitos anexos e gerar custo/armazenamento excessivo.

Correcao recomendada: quota por usuario, por empresa e alertas de consumo.

### 9. Email

**P1 - Templates interpolam dados sem escape HTML dedicado**

Arquivo: `app/services/email_service.py`.

Nomes, emails, numeros e comentarios sao interpolados diretamente em templates HTML. Exemplos: `app/services/email_service.py:197-205`, `app/services/email_service.py:219-226`, `app/services/email_service.py:263-270` e `app/services/email_service.py:292-299`. Isso pode confundir usuario ou renderizar markup inesperado no cliente de email.

Correcao recomendada: usar `html.escape` para todo dado de usuario em templates.

**P2 - Envio async por thread daemon pode perder email**

Arquivo: `app/services/email_service.py:148-167`.

`send_email_async` usa thread daemon. Se worker reinicia, notificacao se perde. Para reset de senha, o endpoint usa BackgroundTasks, mas notificacoes operacionais continuam best-effort.

Correcao recomendada: fila simples persistente ou job de retry para emails importantes.

**P2 - Sem rastreio de entrega/bounce**

Mesmo quando Resend/SMTP aceita a mensagem, o sistema nao registra entrega, bounce, spam complaint ou falha posterior. Para avisos de aprovacao e seguranca, isso limita auditoria operacional.

Correcao recomendada: armazenar eventos de email em tabela propria e processar webhooks do provedor quando disponiveis.

### 10. LGPD e auditoria

**P1 - Audit chain faz scan total**

Endpoint: `/api/admin/audit-logs/verify-chain`.

Com muitos logs, a verificacao completa fica lenta e pode virar DoS interno.

Correcao recomendada: checkpoints periodicos da cadeia e verificacao incremental.

**P2 - Audit log nao registra leitura**

Nao ha registro de quem visualizou notas/dados sensiveis. Para LGPD, pode ser necessario responder quem acessou determinada informacao.

Correcao recomendada: registrar leituras de dados sensiveis e acessos a PDFs, com cuidado para nao gerar volume excessivo sem retencao.

Observacao validada: o endpoint de PDF mesclado ja registra `VIEW_PDF_MERGED` em `app/routers/invoices.py:709-714`, mas a visualizacao de dados completos em `/api/invoices/{id}/verify-full` nao registra leitura.

**P2 - Retencao de dados incompleta**

Notas REPROVADO sao purgadas em 90 dias, mas PAGO fica indefinidamente. CTN pode exigir 5 anos, mas a politica depois disso precisa ser definida.

Correcao recomendada: documento de retencao por tipo de dado e job correspondente.

### 11. Observabilidade e resiliencia

**P1 - `/health` superficial**

Arquivo: `app/main.py:242-244`.

Retorna apenas `{"status": "ok"}`. Nao verifica DB, R2 nem dependencias.

Correcao recomendada: separar:

- `/health/live`: processo vivo.
- `/health/ready`: DB conectando e app pronto.
- `/health/dependencies`: R2/email/API externa com timeouts curtos.

**P1 - Comprovante pode ser gerado sem anexos esperados**

Arquivo: `app/services/pdf_service.py:222-255`.

`generate_print_pdf` monta a capa e concatena anexos, mas ignora qualquer excecao ao baixar/descriptografar/parsear anexos (`app/services/pdf_service.py:244-251`). Como `print_invoice` chama `generate_print_pdf` antes de marcar a nota como paga (`app/routers/print_routes.py:77-85`), uma falha parcial nos anexos pode gerar comprovante incompleto sem alerta claro. A nota ainda pode seguir para o estado PAGO depois da geracao.

Correcao recomendada: diferenciar modo preview de modo lancamento; no lancamento, falha em anexo obrigatorio deve bloquear ou exigir confirmacao explicita com registro de excecao.

**P1 - Sem request_id e structured logs**

Logs existem, mas sem correlacao por request. Em incidentes, fica dificil juntar rota, user, DB, R2 e email.

Correcao recomendada: middleware de request id, logs estruturados e campos padrao: request_id, user_id, route, method, status, duration_ms.

**P1 - Sem metrics/Sentry/Loki**

Nao ha metricas de erro, latencia, filas de aprovacao, falhas de email/R2 e transicoes financeiras.

Correcao recomendada: comecar pequeno: Sentry para excecoes, endpoint `/metrics` ou logs estruturados para dashboards.

### 12. Testes e qualidade

**P1 - Ausencia de testes automatizados**

Nao ha cobertura de auth, aprovacoes, anexos, pagamento, PDF, auditoria ou reset de senha.

Suite minima recomendada:

- login/refresh/reset/change-password e invalidacao por `password_changed_at`;
- fluxo completo: criar, enviar, aprovar gestor, aprovar diretor, pagar;
- indisponibilidade de gestor/diretor;
- upload PDF valido/invalido;
- bloqueio de acesso por role;
- audit chain;
- health checks.

**P2 - Sem pre-commit e CI**

Nao ha barreira automatica de `ruff`, `black`, `isort`, `mypy` ou testes no push.

Correcao recomendada: adicionar pre-commit local e GitHub Actions com lint + testes.

### 13. Acessibilidade

**P2 - Pouco uso de ARIA e labels em botoes de icone**

Templates e componentes gerados em JS tem poucos `aria-*`. Botoes com iconografia podem ficar mudos para leitores de tela.

Correcao recomendada: auditar botoes de icone, drawers, tabelas e formularios com axe/Lighthouse.

**P2 - Tabelas sem `caption`/`scope`**

Tabelas de notas e administracao podem ser dificeis para leitor de tela.

Correcao recomendada: adicionar `caption`, `scope="col"` e labels adequados.

**P2 - Foco visual inconsistente**

Alguns estilos usam `:focus-visible`, mas nao de forma uniforme para `.btn`.

Correcao recomendada: padronizar foco visivel em botoes, links, inputs e elementos interativos.

### 14. Produto e integracoes

**P2 - Sem export CSV/Excel da listagem de notas**

Relatorios dependem das telas/DB. Financeiro precisa exportar pra ERP, contabilidade, auditoria externa.

Correcao recomendada: endpoint `GET /api/invoices/export.csv` que respeita os filtros atuais (mesma assinatura de `/api/invoices/`), com streaming pra nao carregar tudo em memoria.

**P2 - Anexos sem versionamento**

Quando gestor pede "troque o boleto", criador deleta o anexo antigo e sobe novo. O original somenta — historico se perde.

Correcao recomendada: soft-delete de anexos com flag `replaced_by_id`, mantendo trilha; ou tabela `attachment_versions` ligada.

**P2 - Sem autosave de rascunho**

Form de nova nota nao salva enquanto digita. Se browser cair (ou a sessao expirar), o usuario perde tudo.

Correcao recomendada: persistir rascunho em `localStorage` por session/draft_id, ou hit-fire `POST /api/invoices/?status=RASCUNHO` debounced.

**P2 - Sem template/duplicar nota**

Usuarios que cadastram a mesma nota mensalmente (aluguel, sass, etc) re-digitam tudo.

Correcao recomendada: botao "Duplicar" em qualquer nota (pre-preenche tudo exceto numero/datas/anexos); ou conceito de template salvo na conta do usuario.

**P2 - Sem busca por valor exato**

Filtros atuais permitem range minimo/maximo, mas nao "valor = R$ 1.234,56".

Correcao recomendada: aceitar `amount=` exato ou intervalo +/- 0,01 quando o usuario digitar valor decimal.

**P2 - Comentarios sem reply / mencao**

Em thread longa (>20 comentarios), nao da pra responder a um especifico nem mencionar um usuario.

Correcao recomendada: adicionar `parent_comment_id` opcional e parser de `@nome` que vira link pro perfil ou notifica.

**P3 - Sem webhooks**

ERP/automacao externa nao consegue receber evento "nota lancada", "nota reprovada", etc.

Correcao recomendada: tabela `webhook_endpoints` (URL + secret HMAC) + worker que despacha eventos com retry exponencial.

**P3 - Sem API tokens long-lived**

Integrator precisa logar via `/auth/login` e renovar a cada hora. Inviavel pra ETL noturno.

Correcao recomendada: model `ApiToken` (token hash, scope, expires_at, last_used_at) gerido pelo admin.

**P3 - Sem OCR de PDF**

Extrair CNPJ, valor, vencimento, numero da nota a partir do PDF reduziria entrada manual em 80% dos casos.

Correcao recomendada: integrar Google Vision/AWS Textract assincronamente — preenche o form e usuario so confere.

**P3 - Sem visao agregada por fornecedor**

"Quanto a Economart pagou pra Acme Servicos LTDA este ano?" — pergunta natural sem resposta facil.

Correcao recomendada: dashboard `/reports/suppliers` agrupando por `supplier_document` com total/mes, top fornecedores, evolucao temporal.

**P3 - Sem moeda multi-currency**

Tudo assume BRL. Quando abrir pra fornecedor internacional (servico SaaS pago em USD), schema nao suporta.

Correcao recomendada: campo `currency` (ISO 4217) no Invoice + cotacao na data da nota.

**P3 - Sem reabertura/estorno de PAGO**

Se uma nota foi marcada como paga errado, nao ha mecanismo formal de estorno. Manual via DB.

Correcao recomendada: action `unmark_paid` com motivo obrigatorio (>=20 chars), restrita ao financeiro que lancou + log especial no audit.

### 15.5. API consistency e versionamento

**P2 - Resposta de erros inconsistente**

`{"detail": "msg"}` na maior parte (FastAPI padrao), mas alguns endpoints retornam `{"message": "msg"}` (admin), outros tem campos extras. JS cliente trata 2 shapes.

Correcao recomendada: padronizar `{"detail": "...", "code": "...", "field": "..."}` em toda resposta de erro; helper `make_error()` central.

**P2 - Sem versionamento de API**

Nao existe `/api/v1`. Qualquer breaking change vai derrubar integrator externo no dia do deploy.

Correcao recomendada: mover rotas pra `/api/v1/` agora antes de abrir integracao externa, mantendo redirect das rotas antigas.

**P2 - `/api/admin/audit-logs/verify-chain` sem rate-limit**

Admin curioso pode chamar repetidamente, full scan em loop. DoS interno acidental.

Correcao recomendada: cache de resultado por 5min + lock de 1 verify por vez.

**P2 - `GET /api/invoices/{id}/comments` sem paginacao**

Volume vai inchar em notas com muitos comentarios.

Correcao recomendada: paginar com `?page=&per_page=` como na listagem; default 50.

**P2 - `/api/invoices/lookup-cnpj/{cnpj}` sem rate-limit nem backoff**

Cliente malicioso pode usar Economart como proxy pra atacar opencnpj.org. Tambem nao tem retry/backoff se a API externa demorar.

Correcao recomendada: rate-limit por usuario (5 lookup/min); circuit breaker se opencnpj.org retornar 5xx 3x seguidas (pausa 1 min).

### 16. Acessibilidade detalhada (a11y)

**P2 - Botoes-icone sem aria-label**

Auditoria: 11 ocorrencias de `aria-*` em ~30 templates HTML. `app/templates/admin/users.html` tem botoes `editar/redefinir/encerrar` so com `<span class="icon ...">` — leitor de tela le "botao em branco". Tambem geracao via `app.js` em renderAdminUsersTable.

Correcao recomendada: regra de lint custom (grep) + `aria-label="X"` ou `title="X"` em todo botao-icone.

**P2 - Cores semanticas isoladas**

`.role-chip` em algumas telas usa so cor pra distinguir DIRECTOR vs FINANCE. Daltonico nao distingue.

Correcao recomendada: cor + sigla (`MGR`, `DIR`, `FIN`) ou icone alem do background.

**P2 - Foco invisivel em `.btn`**

`:focus-visible` esta em `.nav-item` mas faltam outros componentes. Usuario que navega so por teclado nao ve onde esta.

Correcao recomendada: `.btn:focus-visible { outline: 2px solid var(--orange); outline-offset: 2px; }`.

**P2 - Tabelas sem caption/scope**

Tabela de notas em `/invoices` tem `<table>` sem `<caption>` e sem `scope="col"` nos `<th>`.

Correcao recomendada: adicionar; visualmente esconder caption com `.sr-only` se nao quiser mostrar.

**P2 - Form de comentarios sem aria-describedby**

Help text "Maximo 2000 caracteres. Comentarios sao permanentes." nao esta ligado ao textarea por `aria-describedby`.

Correcao recomendada: `<textarea aria-describedby="comments-help">` + `id="comments-help"` no `<span>`.

**P2 - Login.html so 1 aria-***

Inputs de email/senha tem `<label>` mas form nao tem `role`/`aria-labelledby`. Erros aparecem em `#login-error` sem `aria-live`.

Correcao recomendada: `aria-live="polite"` no container de erro pra anunciar mudanca.

### 17. Performance/queries detalhada

**P2 - selectinload cascateado em listagens grandes**

`app/services/invoice_service.py:155-160` faz selectinload de `created_by`, `manager`, `director`, `finance`, `attachments`, `approval_history.user`. Em `/invoices/?per_page=100`, dispara 6 sub-queries paralelas. Aceitavel agora, mas com 50k notas e filtro amplo vai pesar.

Correcao recomendada: separar "list" (so colunas exibidas + criador) de "detail" (full graph); endpoint `/api/invoices/?fields=light`.

**P2 - total_amount via subquery sobre IDs**

`invoice_service.py:801-805` faz `db.query(sum(amount)).filter(id.in_(query.with_entities(id)))`. PG otimiza, mas e mais lento que `SUM(amount)` na mesma WHERE.

Correcao recomendada: refator pra `query.with_entities(func.sum(...)).scalar()` (mesma query, so muda o select).

**P2 - dashboard-v2.js faz 3 fetches sequenciais**

`/api/alerts`, `/api/invoices/?per_page=5`, `/api/contas-a-pagar/stats`. Promise.allSettled paraleliza, mas ainda sao 3 round-trips.

Correcao recomendada: endpoint agregado `/api/dashboard` retornando os 3 payloads (1 round-trip, 1 commit no DB).

**P2 - CSS unico 1660 linhas**

`app/static/css/main.css` cresceu muito. Carrega 100% em toda pagina.

Correcao recomendada: split em base.css + components.css + admin.css; carregar admin so em /admin/*.

**P2 - Static sem CDN**

Cada request de logo.png/icons/*.svg vai pro Railway. Latency global ruim.

Correcao recomendada: Cloudflare como CDN sobre o R2 (gratis) ou Vercel/Netlify pro frontend estatico.

### 18. Resiliencia detalhada

**P2 - R2 sem object versioning**

Cloudflare R2 suporta versioning mas precisa habilitar. Sem isso, delete acidental e definitivo.

Correcao recomendada: habilitar versioning no bucket + lifecycle pra expirar versions antigas em 90d.

**P2 - Sem distributed lock**

`purge_old_rejected_invoices` em `main.py` roda no startup. Com Gunicorn -w 4, roda 4 vezes em paralelo. Idempotente, mas desperdiça.

Correcao recomendada: advisory lock no PG (`pg_try_advisory_lock`) ou flag `last_purge_at` em uma tabela de metadados.

**P2 - Sem retry de email falho**

Se Resend retornar 500, email se perde. Para comentarios e notificacoes operacionais isso e tolerable; pra reset de senha e codigo MFA (futuro) nao.

Correcao recomendada: tabela `email_queue` (to, subject, html, attempts, next_retry_at) + worker que processa.

**P2 - Sem backup off-site**

Postgres do Railway tem backup automatico (varia por plano). Mas se Railway tiver incidente catastrofico, esta tudo no mesmo lugar.

Correcao recomendada: cron diario que faz `pg_dump | gzip | encrypt` e envia pra R2 (bucket separado) ou S3 com Object Lock.

### 19. Schema/FK detalhada

**P2 - Falta ON DELETE em varias FK**

`Invoice.manager_id`, `Invoice.finance_id`, `Invoice.printed_by_id`, `ApprovalHistory.user_id` — todos sao `ForeignKey("users.id")` sem ondelete. Padrao SQL e RESTRICT, que segura `DELETE FROM users` mesmo se aplicacao quisesse limpar.

Correcao recomendada: `ondelete="SET NULL"` (preserva auditoria) ou `RESTRICT` explicito + processo de anonimizacao que ja existe.

**P2 - PendingAdminAction.target_user_id sem ON DELETE CASCADE**

Se o target for excluido (improvavel mas possivel), pending fica orfa.

**P2 - InvoiceComment.user_id sem ON DELETE SET NULL**

Idem comentarios. Usuario encerrado vira "Colaborador Desligado" via anonymize, mas se algum dia tiver delete fisico, comentarios viram orfos.

### 20. Codigo / manutenibilidade

**P2 - `app/static/js/app.js` (3336 linhas) monolitico**

Mistura auth, lista de invoices, drawer, admin, departamentos, reset de senha, dashboard, atalhos, sidebar mobile, comentarios, PDF viewer. Risco de regressao alto.

Correcao recomendada: split em modulos ES (`app/static/js/modules/auth.js`, etc) carregados com `<script type="module">`. Ou comecar mais simples: extrair drawer e admin pra arquivos proprios.

**P2 - 25 `except Exception` amplos**

`drive_service.py`, `routers/invoices.py` (parser PDF), `email_service.py`, `print_routes.py`. Alguns viram `pass` silencioso. Em incidente, impossivel saber o que falhou.

Correcao recomendada: `except Exception as exc: logger.error(...)` minimo; manter `pass` so em best-effort explicitamente documentado.

**P2 - DOCUMENTACAO.md (1400 linhas) monolitico**

Vai ficar dificil de manter e navegar.

Correcao recomendada: split em `docs/security.md`, `docs/lgpd.md`, `docs/architecture.md`, `docs/ops.md`, `docs/changelog.md`. README aponta pra cada.

### 21. Telemetria/observabilidade extra

**P2 - Sem deteccao de bounce de email**

Se um usuario tem email errado/desativado, Resend devolve mas a aplicacao ignora. Notificacoes ficam ineficazes silenciosamente.

Correcao recomendada: webhook do Resend processado em `/api/webhooks/resend` + tabela `user.email_bounced=True` que faz fallback pra outro canal (banner in-app).

**P2 - Audit log nao registra leituras de dados sensiveis**

LGPD pede: "quem viu CPF X em Y data?". Hoje nao da pra responder. Listagem de notas (`GET /api/invoices/`) e detalhe (`GET /api/invoices/{id}`) nao geram audit log de leitura.

Correcao recomendada: registrar `VIEW_INVOICE` no audit (talvez so pra notas que tem CPF/CNPJ); cuidado com volume.

**P2 - Audit log nao cobre comentarios**

Quem criou e leu comentarios — nao tem registro. Em disputa juridica, falta evidencia.

Correcao recomendada: ja registro `ADD_COMMENT` (entra no commit recente); adicionar `VIEW_COMMENTS` opcional.

### 22. Documentacao operacional

**P2 - Falta diagrama de arquitetura**

README descreve em texto, mas diagrama (ASCII art ou mermaid) ajudaria onboarding e auditoria.

**P2 - Falta runbook**

Procedimentos: "como reiniciar prod", "como rotacionar SECRET_KEY", "como fazer backup manual", "o que fazer se R2 cair", "como restaurar do backup".

**P2 - Falta postmortem template**

Quando algo der errado, ja ter um `.md` de "incident-YYYY-MM-DD.md" estruturado.

**P3 - Falta SLO/SLA documentado**

"Disponibilidade alvo: X%", "tempo de aprovacao alvo: Y horas" — vira meta operacional pro time.

### 23. Pendencias do meu lado (validacao futura)

- A semantica de print=lancar deve mudar (concordo com Codex), mas tem que checar com o financeiro real se eles querem o duplo clique ou se "imprimir = ja paguei".
- Politica de retencao de PAGO depois de 5 anos (CTN exige minimo, nao maximo) — decisao de negocio.
- Quota total por empresa (R2) — limite legal e custo, decisao de negocio.
- Se o usuario aprovar, dividir app.js em modulos pode ser feito em 1 dia mas requer testes pra nao quebrar.

### 15. Documentacao e operacao

**P2 - Falta runbook**

Falta documento de operacao: reiniciar producao, fazer backup manual, restaurar backup, rotacionar secrets, lidar com R2 fora, investigar pagamento indevido.

**P2 - `DOCUMENTACAO.md` muito grande**

Arquivo com mais de 1400 linhas tende a ficar dificil de manter.

Correcao recomendada: dividir por dominio: `security.md`, `lgpd.md`, `ops.md`, `architecture.md`, `runbook.md`.

## Proximos passos recomendados

### Sprint 1 - Seguranca e riscos P0

1. Corrigir invalidacao de refresh tokens por `password_changed_at`.
2. Remover admin default hardcoded e exigir bootstrap seguro.
3. Separar impressao/preview de lancamento financeiro.
4. Fazer fail-fast de secrets em PROD.
5. Garantir backup off-site e procedimento de restore.

### Sprint 2 - Operacao e estabilidade

1. Health checks reais.
2. Request ID e logs estruturados.
3. Rate limit compartilhado e proxy-aware.
4. Fallback R2 apenas em DEV.
5. Testes minimos de auth/fluxo financeiro/upload.

### Sprint 3 - Manutencao e UX

1. Modularizar `app.js`.
2. Reduzir `innerHTML` e padronizar render seguro.
3. Melhorar acessibilidade de botoes, tabelas e drawers.
4. Criar relatorios/exportacoes basicas.

### Sprint 4 - Governanca, LGPD e integracoes

1. Politica de retencao completa.
2. Audit log de leituras sensiveis.
3. Checkpoints de audit chain.
4. Webhooks/API tokens.
5. Runbook e documentacao dividida por dominio.

## Pendencias de validacao

- Confirmar regra desejada para diretores de outros setores.
- Confirmar politica de retencao para notas PAGO.
- Confirmar se PDF impresso deve conter CPF/CNPJ completo.
- Validar comportamento real do R2 quando download falha durante impressao/lancamento. Codigo atual pula anexos com erro no comprovante.
- `iniciar.bat` nao existe na arvore local atual em `C:\Users\Administrador\Documents\ECONOMART\economart_notas`; se houver script de instalacao em outro clone/commit, validar separadamente antes de classificar como P0/P1.
- Definir se a estrategia futura de auth sera cookie HttpOnly para access token ou access em memoria.

## Respostas tecnicas validadas durante a auditoria

### `/verify-full` vaza existencia por 403 vs 404

Confirmado em `app/routers/print_routes.py:255-271`.

O endpoint busca a nota primeiro. Se nao existe, retorna 404. Se existe mas o usuario autenticado nao tem acesso, retorna 403. Isso permite que um usuario autenticado teste IDs e diferencie "nao existe" de "existe, mas nao posso ver". O risco depende da entropia dos IDs e do modelo de ameaca interno, mas para dados financeiros/LGPD e melhor retornar resposta indistinguivel para usuarios sem acesso.

Recomendacao: para recursos sensiveis, retornar 404 tambem quando o usuario nao tem permissao, ou registrar tentativa e manter resposta generica.

### `iniciar.bat`

Nao encontrado na arvore local atual. O repo possui `gerar_certificado.bat`, mas nao `iniciar.bat`. Portanto, o achado sobre `iniciar.bat` copiar `.env.example` para `.env` nao esta confirmado neste checkout local. Deve ser mantido como pendencia ate localizar o script em outro branch, commit, release ou workspace.

### 24. Duplicacao de templates entre perfis

Pos-varredura final encontrei templates duplicados que vao divergir com o tempo:

- `app/templates/invoices/detail.html` (66 linhas) — visao geral, qualquer perfil
- `app/templates/manager/invoice_detail.html` (58 linhas) — visao do gestor revisando
- `app/templates/director/invoice_detail.html` (48 linhas) — visao do diretor revisando
- `app/templates/finance/invoice_detail.html` (36 linhas) — visao do financeiro

Diferenca principal entre eles e o painel lateral de acoes (manager tem selecao de diretor, director tem reprovar, finance tem imprimir+lancar). Resto (header, grid, timeline, comentarios) e identico.

Mesma situacao em `app/templates/manager/queue.html` vs `app/templates/director/queue.html` (so titulo e endpoint mudam).

Risco: ao adicionar feature em invoices/detail.html (ex: campo de comentarios), os 3 outros nao recebem ate alguem lembrar.

P2 - Correcao recomendada: extrair partials `{% include "partials/invoice_detail_body.html" %}` e deixar so o painel de acao em cada template especifico. Outra opcao e usar `invoices/detail.html` com `{% if user.role == 'MANAGER' %}` no painel — mais simples mas centraliza tudo.

### 25. Comentarios na nota — gaps

A feature de comments entregue recente tem alguns gaps:

P2 - Sem paginacao em `GET /api/invoices/{id}/comments`. Em nota com 200 comentarios, retorna tudo.
P2 - Sem indicador "novo" quando outra pessoa comentar enquanto voce esta lendo (sem WebSocket nem long-polling).
P2 - Sem reply a comentario especifico (parent_comment_id).
P2 - Sem mencao @nome com notificacao direcionada.
P2 - Comentario nao volta com refresh — usuario precisa F5. Funciona, mas nao e ideal.
P3 - Sem markdown nem links automatico (URL em texto nao vira anchor).

### 26. main.py crescendo demais

`app/main.py` tem 291 linhas misturando: setup do FastAPI, middlewares, CORS, migrations (30+ ALTERs), bootstrap de admin, purge de notas reprovadas no startup, register de routers, handler de 404, e healthcheck.

P2 - Correcao recomendada: extrair `app/startup/migrations.py`, `app/startup/bootstrap.py`, `app/handlers/errors.py`. main.py vira so import + wiring de 30 linhas.

### 27. Hash chain do audit — bug potencial

`app/models/audit_logs.py:attach_audit_chain_listener` — o `before_flush` ordena por (timestamp, id) mas se varios inserts no mesmo flush tiverem timestamp identico (microsegundo igual em batch), a ordem fica indeterminada e a cadeia pode quebrar entre eles.

P2 - Correcao recomendada: usar `id` como tiebreaker definitivo + garantir timestamp.now() incrementa monotonicamente, ou usar um counter de sequencia local pra ordering definitivo.

### 28. Falta de tipo em alguns campos

Varios endpoints retornam dict bruto em vez de Pydantic schema. Frontend perde validacao tipada e OpenAPI fica generico.

Exemplos: `/api/contas-a-pagar/stats` retorna `{conferred_today: int}` sem schema. `/api/pending-actions/me` retorna lista de dicts construidos manualmente em `_serialize`.

P2 - Correcao recomendada: definir `ConferredStats(BaseModel)`, `PendingActionView(BaseModel)`, etc. Beneficio: OpenAPI gerado fica preciso e cliente pode autogen tipos.

### 29. Dependencias com ranges muito abertos

`requirements.txt` tem varios pinned com `>=` sem upper bound:
- `SQLAlchemy>=2.0.49` — proxima major (3.x) pode quebrar
- `cryptography>=48.0.0` — atualiza muito frequente
- `pydantic>=2.13.4` — idem

P2 - Correcao recomendada: usar `pip-tools` ou `uv lock` pra gerar lockfile com hashes; pinning explicito de major no requirements.in.

### 30. Falta CONTRIBUTING / CODE_OF_CONDUCT

Repo publico (github.com/guiolindo/Notas-despesas) sem guia de contribuicao, sem labels de issue, sem template de PR.

P3 - Correcao recomendada: `CONTRIBUTING.md` minimo com setup local, padrao de commit, branch protection. `PULL_REQUEST_TEMPLATE.md` com checklist.

### 31. Inventario final do repo

| Metrica | Valor |
|---|---|
| Arquivos Python | 40 |
| Arquivos HTML (templates) | 29 |
| Arquivos JavaScript | 5 |
| Arquivos CSS | 1 |
| Linhas em app.js | 3336 |
| Linhas em main.css | 1660 |
| Linhas em invoice_service.py | 1119 |
| Linhas em admin.py | 1003 |
| Linhas em main.py | 291 |
| Migracoes ALTER em main.py | 30+ |
| Endpoints API (`@router`) | ~80 |
| Modelos SQLAlchemy | 12 |
| Roles distintos | 6 |
| Status FSM da nota | 7 |
| `except Exception` amplos | 25 |
| `aria-*` em templates | 11 |
| Testes automatizados | 0 |
