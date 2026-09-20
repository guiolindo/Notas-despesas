# Auditoria Técnica Consolidada — Sistema Economart (Aprovação de Notas Fiscais)

**Data:** setembro/2026 (consolidação)
**Escopo:** backend, frontend, banco de dados, infraestrutura, segurança, escalabilidade
**Commit auditado:** `5aa7a40` (main)
**Perfil de análise:** ambiente corporativo de grande porte, milhares de usuários simultâneos
**Metodologia:** revisão estática de 100% do código-fonte Python/JS, configurações de deploy, schema de banco, templates e suíte de testes.

## Nota sobre auditoria cruzada

Este documento consolida duas auditorias independentes:

- **Auditoria A (estática, este autor).** Revisão completa de código-fonte, 63 achados originais.
- **Auditoria B (Manus AI, 19/08/2026).** Auditoria dinâmica executada em Ubuntu 24.04 com a aplicação de fato rodando em `127.0.0.1:7145`. Exercitou todos os perfis via UI, mediu cobertura de testes (71% em 4.683 linhas), rodou suíte real (106 testes passando em ~130s) e executou pentest não-destrutivo com PDFs adversariais.

**A auditoria dinâmica encontrou um achado crítico não coberto pela auditoria estática** — o guard de sessão em cookie ignora `session_invalidated_at`. Verifiquei o código-fonte e confirmo: `page_auth.py:44` só chama `token_is_pre_password_change`, e `/auth/refresh` em `auth_session.py:170` idem. O mecanismo `token_is_pre_logout` existe em `dependencies.py:60` e só é aplicado em `get_current_user` (Bearer). Um refresh token copiado antes do logout continua renovando access tokens e abrindo páginas HTML depois do logout. Está catalogado abaixo como **SEC-20** e promovido a **crítico**, elevando o total de críticos para seis.

Outros achados novos da auditoria dinâmica, todos verificados neste código: **SEC-20** (logout bypass), **WEB-01/FE-05** (verify autenticado quebrado — template só carrega `verify.js` sem `core-auth.js`), **APP-01** (criação de nota em DEV sem `MASTER_ENCRYPTION_KEY` retorna HTTP 500), **API-01/DOC-01** (rotas documentadas divergem das reais em cinco padrões distintos), **FE-06/FE-07** (atalhos `g i`/`g a` falham; colagem de labels na tabela admin), **QA-03** (pytest ausente em requirements), **QA-04** (cobertura desigual — `attachments.py` em 17%, `page_auth.py` em 28%), **INFRA-09** (quatro migrações SQLite específicas tratadas como warning), **INFRA-10** (warning de bcrypt trapped no startup), **UX-02 a UX-05** (link Reativar sem clique, offline sem retorno, sem botão de verificar cadeia, timer forgot-password suspeito).

Achados que ambas as auditorias encontraram independentemente aparecem marcados com **[convergente]** — servem como sinal de que a evidência é sólida. Notáveis: BE-03 (mark-paid duplicado), SEC-10 (fail-open no parse de PDF), DB-02 (migrações SQLite tratadas como warnings).

**Estatísticas atualizadas:** total sobe de 63 para **78** achados. Críticos: 6 (era 5). O grande incremento veio de **QA/documentação e UX operacional**, categorias que a auditoria estática pura tem dificuldade de flagrar sem rodar o sistema. Notas por dimensão preservadas — os novos achados não mudam a foto agregada, mas mudam a lista do que precisa ser corrigido antes de produção.

---

## Índice

1. [Resumo executivo](#1-resumo-executivo)
2. [Estatísticas da auditoria](#2-estatísticas-da-auditoria)
3. [Achados — Segurança](#3-achados--segurança)
4. [Achados — Banco de Dados](#4-achados--banco-de-dados)
5. [Achados — Backend](#5-achados--backend)
6. [Achados — Arquitetura](#6-achados--arquitetura)
7. [Achados — Frontend](#7-achados--frontend)
8. [Achados — Infraestrutura](#8-achados--infraestrutura)
9. [Achados — Performance e Escalabilidade](#9-achados--performance-e-escalabilidade)
10. [Achados — Confiabilidade](#10-achados--confiabilidade)
11. [Achados — Qualidade de Código](#11-achados--qualidade-de-código)
12. [Priorização consolidada](#12-priorização-consolidada)
13. [Riscos para produção](#13-riscos-para-produção)
14. [Análise de escalabilidade (10x / 100x)](#14-análise-de-escalabilidade-10x--100x)
15. [Recomendações estratégicas](#15-recomendações-estratégicas)
16. [Roadmap sugerido](#16-roadmap-sugerido)
17. [Conclusão — maturidade técnica](#17-conclusão--maturidade-técnica)

---

## 1. Resumo executivo

O Economart é uma aplicação FastAPI monolítica bem construída para o estágio em que está. O código demonstra **maturidade de segurança acima da média** para um projeto deste porte: JWT com access em memória, refresh em cookie HttpOnly, hash chain em audit logs, pseudonimização de IP para LGPD, criptografia client-side de PDFs antes do upload, CSP sem `unsafe-inline` em scripts, e uma suíte de 106 testes automatizados. Houve investimento real e visível em segurança, com três rodadas de pentest documentadas e nove vulnerabilidades corrigidas.

Dito isso, **o sistema não está pronto para o cenário descrito** (ambiente corporativo, milhares de usuários simultâneos). Os problemas não são de codificação — são de **arquitetura operacional e escalabilidade**. Três categorias dominam o risco:

**Primeiro, o sistema não escala horizontalmente de forma segura.** Rate limiting vive em um dicionário na memória do processo; com dois workers gunicorn o limite efetivo já é o dobro do configurado, e com réplicas múltiplas o bypass é linear. A hash chain de audit logs faz um `SELECT` da última linha a cada flush — dois workers inserindo concorrentemente leem o mesmo antecessor, bifurcam a cadeia, e o endpoint de verificação passa a reportar violação permanente e irreversível. As migrações de schema rodam como DDL solto no import do módulo, sem tabela de versão e sem lock distribuído.

**Segundo, há gargalos de performance que se tornam falhas em carga.** O endpoint `/alerts/` executa cinco queries sem paginação, retornando todas as notas de cada categoria, e é invocado no `initShell()` de toda página autenticada. Um diretor com dez mil notas vencidas recebe um JSON de dez mil linhas a cada navegação. A listagem principal carrega eagerly o histórico de aprovação e os anexos de cada nota — com `per_page=100` são duzentas subqueries. O modo `light` existe no backend mas o frontend nunca o utiliza. A geração de PDF baixa e descriptografa todos os anexos sincronamente dentro do request, bloqueando o worker por segundos.

**Terceiro, não existe rede de proteção operacional.** Não há CI/CD — os 106 testes só rodam se alguém lembrar de executá-los. Não há observabilidade além de logs em stdout: sem Sentry, sem métricas, sem alertas. O healthcheck configurado (`/health`) retorna 200 incondicionalmente, então o orquestrador nunca removerá do balanceador um pod com banco de dados caído. Não há backup verificado nem procedimento de recuperação testado.

Do lado de segurança, o achado mais grave foi trazido pela auditoria dinâmica cruzada e confirmado por revisão de código: **o logout não revoga o refresh token nem invalida o page guard**. A infraestrutura para isso existe no código (`session_invalidated_at`, `token_is_pre_logout`) mas é aplicada apenas em um dos três caminhos de autenticação — o header `Authorization: Bearer`. Os caminhos que usam o cookie (`/auth/refresh` e todas as páginas HTML) checam apenas mudança de senha, não logout. Um refresh token capturado antes do logout continua válido por sete dias, apesar de o usuário ter clicado em "sair". Outros achados graves: **credenciais de administrador padrão hardcoded** no código versionado (`admin@economart.com` / `Admin@2024!`), a **"assinatura digital" dos comprovantes ser um SHA-256 sem segredo** — qualquer pessoa que conheça quatro campos públicos da nota forja a assinatura, o que compromete a promessa de autenticidade impressa no próprio PDF —, e a **ausência de rate limit no endpoint público `/verify/{id}`**, que permite enumeração ilimitada.

**Avaliação geral: 5,8/10** (levemente rebaixada de 6,0 após SEC-20). Boa base de código, segurança consciente porém com gap crítico na revogação de sessão, débito operacional alto. Com 4 a 6 semanas de trabalho focado nos itens de prioridade imediata e curto prazo — começando pela correção de SEC-20 —, o sistema chega confortavelmente a um patamar de produção corporativa.

---

## 2. Estatísticas da auditoria

| Métrica | Valor |
|---|---|
| Arquivos Python analisados | 64 |
| Arquivos JavaScript analisados | 24 |
| Templates Jinja2 analisados | 31 |
| Linhas de código backend (aprox.) | 8.900 |
| Linhas de código frontend (aprox.) | 4.600 |
| Endpoints HTTP mapeados | 78 |
| Testes automatizados existentes | 106 (auditoria B mediu 71% de cobertura) |
| **Total de achados (consolidado)** | **78** |
| Achados exclusivos da auditoria A (estática) | 60 |
| Achados exclusivos da auditoria B (Manus, dinâmica) | 15 |
| Achados convergentes (independentes) | 3 |

### Distribuição por severidade (consolidada)

| Severidade | Quantidade | % |
|---|---|---|
| Crítica | 6 | 8% |
| Alta | 25 | 32% |
| Média | 31 | 40% |
| Baixa | 13 | 17% |
| Informativa | 3 | 3% |

### Distribuição por categoria

| Categoria | Quantidade |
|---|---|
| Segurança | 19 |
| Banco de Dados | 10 |
| Backend | 8 |
| Infraestrutura | 8 |
| Performance / Escalabilidade | 7 |
| Arquitetura | 5 |
| Frontend | 4 |
| Qualidade de Código | 2 |

---

## 3. Achados — Segurança

### SEC-01 — Credenciais de administrador padrão hardcoded no código versionado

**Severidade:** Crítica
**Categoria:** Segurança
**Prioridade:** Imediata

**Evidência**
`app/migrations.py`, função `ensure_admin_exists()`. Quando a tabela `users` está vazia, o sistema cria automaticamente um usuário com e-mail `admin@economart.com` e senha `Admin@2024!`, ambos literais no código-fonte. O repositório está hospedado no GitHub (`guiolindo/Notas-despesas`) e o `README.md` documenta explicitamente essa credencial na seção "Setup local".

**Impacto**
Qualquer pessoa com acesso ao repositório — colaborador atual, ex-colaborador, ou terceiro caso o repositório se torne público — conhece a credencial de administrador de qualquer instância recém-provisionada. A mitigação existente (`must_change_password=True`) força a troca no primeiro login, mas cria uma janela de exposição entre o momento do deploy e o primeiro acesso legítimo. Um atacante que monitore o domínio e acesse antes do administrador legítimo assume controle total: cria usuários, altera papéis, lê toda a base de notas fiscais. Em ambiente corporativo isso é comprometimento completo do sistema financeiro.

**Recomendação**
Remover o seed automático de credenciais do código. Substituir por uma das abordagens: exigir variáveis de ambiente `BOOTSTRAP_ADMIN_EMAIL` e `BOOTSTRAP_ADMIN_PASSWORD` sem valores padrão (aplicação recusa subir sem elas na primeira execução); ou gerar uma senha aleatória no primeiro boot e imprimi-la uma única vez no log de startup; ou fornecer um comando CLI separado de provisionamento que o operador executa manualmente. Independentemente da escolha, remover a credencial do README e rotacionar imediatamente a senha em qualquer ambiente já provisionado.

---

### SEC-02 — "Assinatura digital" do comprovante é hash sem segredo

**Severidade:** Crítica
**Categoria:** Segurança
**Prioridade:** Imediata

**Evidência**
`app/services/pdf_service.py`, função `invoice_hash()`. O valor é calculado como `sha256(f"{invoice.id}:{invoice.invoice_number}:{invoice.amount}:{invoice.created_at}")[:16].upper()`. Não há chave secreta envolvida. Esse valor é impresso no comprovante PDF sob o rótulo **"Assinatura Digital"**, acompanhado do texto *"Este documento possui validade mediante verificação do QR Code"*, e é retornado publicamente pelo endpoint `/verify/{invoice_id}` no campo `auth_hash`.

**Impacto**
A assinatura não autentica nada. Todos os quatro campos que a compõem são obteníveis: o `id` está na URL do QR code, o número e o valor aparecem no próprio comprovante, e o `created_at` pode ser inferido ou obtido via API. Um fornecedor mal-intencionado ou colaborador interno pode forjar um comprovante de aprovação visualmente idêntico ao legítimo, incluindo uma "assinatura digital" que passa em qualquer conferência manual. Como o documento é usado para liberar pagamentos, isso viabiliza fraude financeira direta. Adicionalmente, o truncamento em 16 caracteres hexadecimais (64 bits) enfraquece ainda mais a construção, embora esse não seja o problema principal — a ausência de segredo é.

**Recomendação**
Substituir por HMAC-SHA256 utilizando uma chave dedicada (não reaproveitar a `SECRET_KEY` do JWT). A verificação de autenticidade deve ocorrer server-side: o QR code aponta para `/verify/{id}`, e é o servidor — que possui a chave — quem confirma a validade. O valor exibido no papel deve ser apenas um identificador de conferência, nunca apresentado ao usuário como prova criptográfica autônoma. Revisar também o texto impresso no PDF para não prometer garantia que a construção não oferece.

---

### SEC-03 — Endpoint público `/verify/{id}` sem rate limit

**Severidade:** Crítica
**Categoria:** Segurança
**Prioridade:** Imediata

**Evidência**
`app/routers/print_routes.py`, rota `GET /verify/{invoice_id}`. Não exige autenticação e não consta em `RATE_LIMIT_POLICIES` (`app/middleware/security.py`), que cobre apenas cinco padrões: `auth-login`, `auth-forgot-password`, `auth-reset-password`, `lookup-cnpj` e `invoice-comments`.

**Impacto**
Enumeração ilimitada. Embora os identificadores sejam UUIDv4 (espaço de busca inviável para força bruta cega), qualquer vazamento parcial de IDs — logs de proxy, histórico de navegador, e-mails encaminhados, QR codes fotografados — permite consulta em massa sem qualquer barreira. Cada requisição executa uma query com cinco `selectinload`, renderiza um template Jinja e calcula um hash: é um vetor de negação de serviço de baixo custo para o atacante e alto custo para o servidor. Adicionalmente, os dados retornados, ainda que mascarados, revelam status da nota, valor exato, setor e data de aprovação — informação competitiva sensível quando agregada.

**Recomendação**
Adicionar política de rate limit específica para rotas públicas de verificação, com janela por IP mais restritiva que a das rotas autenticadas. Considerar CAPTCHA ou proof-of-work leve após um número baixo de consultas na mesma janela. Avaliar se o valor monetário precisa aparecer sem autenticação — a verificação de autenticidade pode se limitar a "esta nota existe e está aprovada" sem expor o montante.

---

### SEC-04 — Rate limit em memória por processo

**Severidade:** Alta
**Categoria:** Segurança / Escalabilidade
**Prioridade:** Imediata

**Evidência**
`app/middleware/security.py`, variável global `rate_limit_buckets: dict[str, list[datetime]]`. O estado é mantido no espaço de memória de cada processo Python. O `Procfile` e o `railway.toml` configuram `gunicorn -w 2`, ou seja, dois processos independentes.

**Impacto**
Com dois workers, o limite efetivo é o dobro do configurado — a política `auth-login` de "5 tentativas por 60 segundos" torna-se, na prática, 10, pois o balanceamento distribui as requisições entre processos que não compartilham contador. Se a aplicação for escalada para múltiplas réplicas, o bypass cresce linearmente com o número de instâncias. O estado é volátil: qualquer restart, deploy ou crash zera todos os contadores, permitindo que um atacante bloqueado retome imediatamente. A função `_sweep_expired` só limpa buckets quando o dicionário ultrapassa mil chaves, permitindo crescimento de memória não limitado sob ataque distribuído de origens variadas.

**Recomendação**
Migrar o rate limiting para armazenamento compartilhado — Redis é a escolha natural, usando estruturas de janela deslizante ou token bucket com expiração automática de chaves. Alternativamente, aplicar rate limiting na camada de borda (Cloudflare, proxy reverso), que também protege contra tráfego que sequer chega à aplicação. Manter o limite em memória apenas como defesa secundária.

---

### SEC-05 — Cobertura de rate limit insuficiente

**Severidade:** Alta
**Categoria:** Segurança
**Prioridade:** Curto prazo

**Evidência**
`app/middleware/security.py`, tupla `RATE_LIMIT_POLICIES`. Cobre cinco padrões de rota. Ficam descobertos, entre outros: `POST /api/invoices/` (criação de notas com upload), `POST /auth/refresh`, `POST /auth/change-password`, todos os endpoints sob `/api/admin/*`, `GET /alerts/`, `GET /api/invoices/` e `POST /api/pending-actions/run-due`.

**Impacto**
Um usuário autenticado, ainda que legítimo, pode saturar recursos: criar notas em loop consumindo armazenamento no R2 e CPU de validação de PDF; invocar `/alerts/` repetidamente disparando cinco queries pesadas por chamada; martelar `/auth/refresh` gerando tokens indefinidamente. Uma conta comprometida se transforma em vetor de negação de serviço interno. Endpoints administrativos sem limite também facilitam varredura automatizada por um insider.

**Recomendação**
Estabelecer uma política padrão aplicável a todas as rotas autenticadas, com limites generosos o suficiente para não afetar uso legítimo, e políticas mais restritivas para operações caras (upload, geração de PDF, alertas). Diferenciar o identificador de bucket por usuário autenticado, não apenas por IP, para que um escritório inteiro atrás de NAT não compartilhe o mesmo contador.

---

### SEC-06 — `X-Forwarded-For` confiado sem validação de proxy

**Severidade:** Alta
**Categoria:** Segurança
**Prioridade:** Curto prazo

**Evidência**
`app/middleware/security.py`, função `_client_ip()`. Quando `ENVIRONMENT` é `PROD`, o código lê o primeiro elemento do header `X-Forwarded-For` e o utiliza como identidade do cliente, sem verificar se a requisição de fato veio de um proxy confiável.

**Impacto**
Se a aplicação for exposta diretamente, ou se o proxy for configurado para acrescentar em vez de sobrescrever o header, um atacante forja `X-Forwarded-For` com valores aleatórios a cada requisição e contorna completamente o rate limit — cada requisição cai em um bucket distinto. O mesmo valor forjado é gravado nos logs de auditoria (após pseudonimização), corrompendo a trilha forense: um incidente investigado apontará para IPs que nunca existiram. Como os audit logs são o mecanismo de prestação de contas do sistema, isso compromete o controle de detecção mais importante.

**Recomendação**
Manter uma lista de redes confiáveis de proxy e só honrar o header quando o endereço do socket pertencer a ela. Quando houver múltiplos hops, extrair o IP na posição correta a partir da direita, contando o número conhecido de proxies. Registrar tanto o IP do socket quanto o valor derivado do header nos audit logs, permitindo reconciliação posterior.

---

### SEC-07 — Falha aberta quando `ENVIRONMENT` não está definido

**Severidade:** Alta
**Categoria:** Segurança / Configuração
**Prioridade:** Curto prazo

**Evidência**
`app/config.py` define `ENVIRONMENT: str = "DEV"` como padrão. Diversos controles de segurança dependem desse valor ser exatamente `PROD`: exposição de `/docs`, `/redoc` e `/openapi.json` (`app/main.py`), flag `Secure` no cookie de refresh (`app/routers/auth_session.py`), restrição de CORS (`app/main.py`), proteção de `/health/dependencies` (`app/health.py`) e interpretação de `X-Forwarded-For`.

**Impacto**
O padrão é o modo inseguro. Um erro de configuração no painel do Railway, uma variável renomeada, ou um novo ambiente provisionado sem a variável faz o sistema subir com: documentação completa da API exposta publicamente (78 endpoints com schemas), cookies de sessão transmitidos sem a flag `Secure` (interceptáveis em conexão não-TLS), CORS aceitando qualquer origem, e endpoint de diagnóstico revelando quais provedores estão configurados. Nenhum alarme é disparado — o sistema funciona normalmente, apenas inseguro. Este é o padrão clássico de *fail-open*, oposto ao princípio de configuração segura por padrão.

**Recomendação**
Inverter a lógica: tratar como produção salvo indicação explícita em contrário, ou tornar a variável obrigatória sem valor padrão, com a aplicação recusando-se a iniciar quando ausente. O mecanismo `startup_security_failure()` já existente para `SECRET_KEY` e `MASTER_ENCRYPTION_KEY` pode ser estendido para cobrir `ENVIRONMENT`. Adicionar um log de startup destacado informando em qual modo a aplicação subiu.

---

### SEC-08 — `POST /api/pending-actions/run-due` acessível a qualquer usuário autenticado

**Severidade:** Alta
**Categoria:** Segurança / Controle de Acesso
**Prioridade:** Curto prazo

**Evidência**
`app/routers/pending_actions.py`, endpoint `run_due_endpoint`. A única dependência é `get_current_user` — não há verificação de papel. A função executa `run_due_actions()`, que percorre todas as ações administrativas pendentes com prazo vencido e aplica seus efeitos, incluindo desativação de contas de diretores (`_execute_action`).

**Impacto**
Um funcionário comum pode disparar a execução de ações administrativas sensíveis. O mecanismo de janela de 24 horas foi projetado como defesa contra administrador malicioso, dando tempo para que diretores contestem uma desativação. Embora o endpoint só execute ações cujo prazo já expirou — não permitindo antecipação —, ele quebra o modelo de responsabilidade: a auditoria não registrará quem forçou a execução, e o desenho pressupõe que essa varredura seja uma tarefa de sistema. O mesmo problema, de forma mais sutil, ocorre em `GET /api/pending-actions/me` e `GET /api/pending-actions/visible`, que invocam `run_due_actions()` internamente — endpoints de leitura executando mutação de estado, violando semântica HTTP e permitindo que qualquer prefetch de navegador ou crawler dispare desativações de contas.

**Recomendação**
Restringir o endpoint a papéis administrativos, ou removê-lo da API pública e transformá-lo em tarefa agendada executada por um scheduler dedicado. Extrair a chamada de `run_due_actions()` dos endpoints `GET`, garantindo que operações de leitura não produzam efeitos colaterais.

---

### SEC-09 — Injeção de HTML em templates de e-mail

**Severidade:** Alta
**Categoria:** Segurança
**Prioridade:** Curto prazo

**Evidência**
`app/services/email_service.py`, funções `template_invoice_rejected`, `template_new_invoice_for_approver`, `template_director_peer_notify` e outras. Todas constroem o corpo HTML via f-string interpolando diretamente valores originados de entrada de usuário — notavelmente `reason` (motivo de reprovação, até 1000 caracteres livres), `invoice_number`, `creator_name` e `supplier_name`. Não há escape de HTML. O mesmo padrão aparece em `app/routers/invoices_comments.py` (corpo do comentário interpolado no e-mail de notificação) e em `app/routers/pending_actions.py`.

**Impacto**
Um gestor que reprova uma nota pode inserir HTML arbitrário no motivo — âncoras apontando para domínios externos, imagens rastreadoras, blocos de texto que imitam comunicação oficial. Esse conteúdo é entregue por e-mail ao criador da nota, vindo de um remetente confiável da própria empresa. É um vetor de phishing interno com credibilidade elevada, difícil de detectar por filtros anti-spam justamente porque a origem é legítima. Clientes de e-mail modernos limitam scripts, mas links e imagens passam normalmente.

**Recomendação**
Escapar todo valor dinâmico antes de interpolar no HTML dos templates. Preferencialmente, migrar a montagem dos e-mails para templates Jinja2 com autoescape habilitado — o projeto já usa Jinja2 para as páginas web e tem autoescape configurado corretamente lá. Manter a versão em texto puro como está, mas validar que não contenha quebras de linha capazes de manipular cabeçalhos.

---

### SEC-10 — Detecção de PDF malicioso contornável

**Severidade:** Alta
**Categoria:** Segurança / Upload de Arquivos
**Prioridade:** Curto prazo

**Evidência**
`app/routers/invoices_helpers.py`, função `check_pdf_safety()`. A verificação inspeciona apenas três locais na estrutura do documento: `/Names → /JavaScript` no catálogo raiz, `/OpenAction` no raiz, e `/AcroForm` no raiz. Além disso, o bloco `try: reader = PdfReader(...) except Exception: return` libera o arquivo quando o parsing falha.

**Impacto**
Três caminhos de bypass. Primeiro, JavaScript declarado em nível de página (dicionário `/AA` de anotações individuais) ou em objetos indiretos não é inspecionado. Segundo, e mais grave, corromper deliberadamente a tabela de referência cruzada faz o `PdfReader` lançar exceção, e o código então **libera o arquivo sem qualquer verificação** — o atacante controla completamente essa condição. Terceiro, streams comprimidos podem esconder conteúdo que só se materializa após descompressão. O arquivo aceito é criptografado, armazenado no R2, e posteriormente concatenado no comprovante oficial distribuído a aprovadores e ao setor financeiro, que o abrirão em leitores desktop — exatamente o ambiente onde JavaScript embutido em PDF é explorável.

**Recomendação**
Inverter a política de falha: PDF que não parseia deve ser rejeitado, não aceito. Complementar a inspeção estrutural com sanitização ativa — reescrever o documento removendo todos os elementos ativos, em vez de tentar detectá-los. Considerar processar uploads em ambiente isolado (container efêmero ou serviço separado) para conter eventual exploração da própria biblioteca de parsing.

---

### SEC-11 — Reuso da `SECRET_KEY` para pseudonimização de IP

**Severidade:** Média
**Categoria:** Segurança / Criptografia
**Prioridade:** Médio prazo

**Evidência**
`app/security/hashing.py`, função `pseudonymize_ip()`. Utiliza `settings.SECRET_KEY` como chave HMAC e trunca o resultado em 16 caracteres hexadecimais (64 bits). A mesma chave assina todos os tokens JWT do sistema.

**Impacto**
Duas consequências. Do ponto de vista criptográfico, reutilizar uma chave para finalidades distintas é má prática — compromete a independência dos mecanismos e complica a rotação. Do ponto de vista de privacidade, a pseudonimização é reversível por quem detiver a chave: o espaço de endereços IPv4 tem apenas 2³² elementos, então construir uma tabela completa mapeando hash para IP é computacionalmente trivial. Isso significa que a proteção LGPD oferecida é nominal — qualquer pessoa com acesso à `SECRET_KEY` (operadores de infraestrutura, ou um atacante que a obtenha) reverte todos os IPs históricos instantaneamente. Operacionalmente, rotacionar a `SECRET_KEY` por qualquer motivo de segurança destrói a correlação de todos os IPs já registrados, inutilizando a trilha de auditoria para investigações retroativas.

**Recomendação**
Introduzir uma chave dedicada exclusivamente à pseudonimização, com ciclo de vida independente. Documentar que a pseudonimização protege contra exposição acidental, não contra adversário com acesso à chave. Para maior robustez, considerar adicionar um sal rotacionado periodicamente, aceitando a perda de correlação entre períodos como trade-off consciente.

---

### SEC-12 — `verify-full` expõe e-mails corporativos sem máscara

**Severidade:** Média
**Categoria:** Segurança / Privacidade
**Prioridade:** Curto prazo

**Evidência**
`app/routers/print_routes.py`, endpoint `GET /api/invoices/{id}/verify-full`. Retorna `manager_email` e `director_email` em texto integral. A função de controle de acesso `_user_has_invoice_access()` concede acesso irrestrito ao papel `CONTAS_A_PAGAR`, que por design enxerga todas as notas do sistema.

**Impacto**
Um usuário com perfil de contas a pagar pode iterar sobre todas as notas e extrair o e-mail corporativo de todos os gestores e diretores da organização. Essa lista é o insumo primário para ataques de phishing direcionado e fraude do tipo "comprometimento de e-mail corporativo", em que o atacante se passa por um diretor para autorizar pagamentos. O papel foi desenhado como somente-leitura para conferência operacional; extrair a estrutura hierárquica completa da empresa vai além dessa necessidade. O mesmo dado aparece impresso no comprovante PDF (`_approval_row` com `show_email=True`), que circula fora do sistema.

**Recomendação**
Aplicar mascaramento de e-mail — a função `_mask_email()` já existe no mesmo arquivo, mas não é utilizada neste retorno. Avaliar por papel qual nível de detalhe é necessário: para conferência de pagamento, o nome do aprovador é suficiente; o e-mail completo só se justifica para quem precisa efetivamente contatá-lo.

---

### SEC-13 — Ausência de proteção CSRF

**Severidade:** Média
**Categoria:** Segurança
**Prioridade:** Médio prazo

**Evidência**
Nenhum token anti-CSRF é emitido ou validado em qualquer ponto do sistema. As páginas HTML autenticam via cookie `refresh_token` (`app/security/page_auth.py`), e o endpoint `POST /auth/refresh` aceita exclusivamente esse cookie, sem exigir cabeçalho adicional.

**Impacto**
O atributo `SameSite=strict` no cookie oferece proteção substancial em navegadores modernos, e a política de CORS impede leitura de respostas cross-origin. O risco residual concentra-se em: navegadores legados ou configurações que não honram `SameSite`; cenários de subdomínio comprometido, onde `strict` não protege; e requisições disparadas por navegação de nível superior. Como o sistema depende inteiramente de uma única camada de defesa, qualquer falha nela expõe operações sensíveis. A avaliação de severidade é média — não alta — porque as APIs de mutação exigem cabeçalho `Authorization`, que não é enviado automaticamente pelo navegador.

**Recomendação**
Adotar o padrão de cookie duplo ou token sincronizado para as rotas que dependem de cookie. Validar o cabeçalho `Origin` nas requisições de mutação como camada complementar. Documentar explicitamente a decisão de depender de `SameSite` caso se opte por não implementar tokens, para que a escolha seja consciente e revisitável.

---

### SEC-14 — Dependência externa não controlada no caminho da requisição

**Severidade:** Média
**Categoria:** Segurança / Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
`app/services/document_service.py`, função `lookup_cnpj()`. Realiza requisição HTTP para `https://api.opencnpj.org/{cnpj}` com timeout de 8 segundos, sincronamente dentro do request do usuário. Não há circuit breaker, e a resposta é gravada diretamente no banco (`CnpjCache`) após truncamento em 255 caracteres.

**Impacto**
Três riscos. Disponibilidade: se a API externa ficar lenta, cada consulta de CNPJ bloqueia um worker por até 8 segundos — com dois workers, dezesseis consultas simultâneas travam a aplicação inteira. Integridade: o conteúdo retornado é persistido sem validação de formato ou sanitização; comprometimento da API de terceiros ou sequestro de DNS injeta dados arbitrários que serão exibidos na interface e impressos em comprovantes. Confidencialidade: cada consulta revela a um terceiro qual CNPJ a empresa está processando, expondo padrão de relacionamento com fornecedores.

**Recomendação**
Mover a consulta para processamento assíncrono, retornando imediatamente ao usuário e preenchendo os dados quando disponíveis. Implementar circuit breaker que suspende chamadas após sequência de falhas. Validar e sanitizar o conteúdo recebido antes de persistir. Reduzir o timeout e considerar fixação de certificado se a criticidade justificar.

---

### SEC-15 — CDN externo sem verificação de integridade

**Severidade:** Média
**Categoria:** Segurança
**Prioridade:** Médio prazo

**Evidência**
`app/middleware/security.py`, cabeçalho CSP: `script-src 'self' https://cdn.jsdelivr.net`. O template `app/templates/contas_a_pagar/scanner.html` carrega `jsQR` desse CDN sem atributo de integridade de subrecurso.

**Impacto**
A política de CSP autoriza a execução de **qualquer** script servido por jsDelivr, não apenas o pacote pretendido. Um comprometimento do CDN, ou do pacote `jsqr` no registro npm que o alimenta, resulta em execução de código arbitrário no contexto da aplicação — com acesso ao token de sessão em memória e capacidade de agir em nome do usuário. A superfície é ampla: jsDelivr serve milhões de pacotes.

**Recomendação**
Adicionar hash de integridade ao carregamento do script, garantindo que apenas o conteúdo esperado execute. Preferencialmente, hospedar a biblioteca localmente junto aos demais assets, eliminando a dependência externa e permitindo remover o domínio da política CSP — a aplicação já vendoriza os ícones Lucide seguindo exatamente esse raciocínio.

---

### SEC-16 — Dados pessoais em logs de aplicação

**Severidade:** Média
**Categoria:** Segurança / LGPD
**Prioridade:** Médio prazo

**Evidência**
`app/services/email_service.py` registra `logger.info(f"[email-smtp] enviado para {to_email}: {subject}")` e variantes em caso de erro. `app/services/email_queue_service.py` registra endereços completos em mensagens de retry e falha. O assunto do e-mail frequentemente contém o número da nota fiscal.

**Impacto**
Endereços de e-mail são dados pessoais sob a LGPD. Os logs do Railway são retidos, acessíveis a qualquer pessoa com acesso ao painel, e potencialmente encaminhados a serviços de agregação. A combinação de e-mail com número de nota fiscal permite reconstruir quem aprovou o quê, fora do sistema de auditoria formal e sem os controles de acesso que ele possui. O sistema demonstra cuidado ao pseudonimizar IPs nos audit logs, mas registra e-mails em texto claro nos logs operacionais — inconsistência de tratamento.

**Recomendação**
Mascarar endereços de e-mail nas mensagens de log, preservando apenas o suficiente para diagnóstico. Utilizar identificadores internos em vez de dados pessoais para correlação. Definir e documentar política de retenção de logs alinhada às demais políticas de privacidade do sistema.

---

### SEC-17 — Cabeçalho `X-XSS-Protection` obsoleto

**Severidade:** Baixa
**Categoria:** Segurança
**Prioridade:** Longo prazo

**Evidência**
`app/middleware/security.py`, `SecurityHeadersMiddleware` define `X-XSS-Protection: 1; mode=block`.

**Impacto**
O cabeçalho foi removido dos navegadores modernos. Em versões antigas do Internet Explorer e Edge legado, o filtro que ele ativava introduziu vulnerabilidades próprias — o mecanismo de bloqueio podia ser abusado para desativar seletivamente scripts legítimos de uma página. A recomendação atual de todos os principais fornecedores é definir o valor como `0` ou omitir o cabeçalho, confiando exclusivamente na CSP.

**Recomendação**
Remover o cabeçalho ou defini-lo como `0`. A CSP já implementada, sem `unsafe-inline` para scripts, é a proteção efetiva.

---

### SEC-18 — Divergência entre limites de valor da aplicação e do banco

**Severidade:** Baixa
**Categoria:** Segurança / Integridade
**Prioridade:** Curto prazo

**Evidência**
`app/models/invoices.py` define `amount = Column(Numeric(10, 2))`, cujo valor máximo é 99.999.999,99. `app/schemas/invoice.py` define `_MAX_INVOICE_AMOUNT = Decimal("10000000000.00")` — dez bilhões.

**Impacto**
Existe uma faixa de valores — entre cem milhões e dez bilhões — que passa na validação da aplicação mas excede a capacidade da coluna. Em PostgreSQL isso gera erro de estouro numérico, resultando em 500 para o usuário e transação abortada. Em SQLite o comportamento é silenciosamente permissivo, criando divergência entre ambientes de desenvolvimento e produção. Não é vulnerabilidade explorável para ganho, mas é uma inconsistência de contrato que produz falha não tratada.

**Recomendação**
Alinhar os dois limites. Definir o teto de negócio primeiro — qual o maior valor plausível de uma nota fiscal na operação — e derivar ambas as definições dele.

---

### SEC-20 — Guard de sessão em cookie ignora invalidação por logout **[novo — Manus]**

**Severidade:** Crítica
**Categoria:** Segurança / Autenticação
**Prioridade:** Imediata

**Evidência**
Três caminhos processam autenticação com semânticas divergentes:

- `app/security/dependencies.py:124` — `get_current_user` (usado por endpoints com header `Authorization: Bearer`) chama `token_is_pre_logout()` e rejeita tokens emitidos antes de `session_invalidated_at`.
- `app/routers/auth_session.py:170` — `POST /auth/refresh` (usado pelo cookie `refresh_token`) chama apenas `token_is_pre_password_change()`. Não verifica logout.
- `app/security/page_auth.py:44` — `_get_user_from_cookie` (usado pelos page guards das rotas HTML) chama apenas `token_is_pre_password_change()`. Não verifica logout.

A infraestrutura de invalidação existe. O endpoint de logout grava `current_user.session_invalidated_at = datetime.now(timezone.utc)` (auth_session.py:201). A função `token_is_pre_logout` está implementada corretamente. Ela simplesmente não é chamada nos dois caminhos que usam o cookie de refresh.

**Impacto**
Um refresh token capturado antes do logout continua válido por sete dias (o tempo de expiração configurado). Um atacante que tenha exfiltrado o cookie — via XSS residual, cópia em máquina compartilhada, comprometimento temporário de dispositivo, ou log de proxy — mantém sessão persistente **apesar** do usuário ter realizado logout explícito. A UI comunica ao usuário "você saiu com segurança"; a realidade é que o botão de logout, para o principal vetor de captura, é decorativo.

O impacto se materializa em dois lugares: `/auth/refresh` retorna 200 e emite novo access token; qualquer página HTML (`/dashboard`, `/admin/*`, `/invoices/*`, etc.) abre normalmente porque o page guard aceita o cookie. A auditoria dinâmica do Manus reproduziu exatamente esse cenário: refresh token restaurado após logout retornou 200 e abriu `/admin/users`.

Este é um controle documentado no README como implementado. O gap entre promessa e comportamento é o problema — usuários e revisores acreditam estar protegidos por um mecanismo que só protege um dos três caminhos.

**Recomendação**
Chamar `token_is_pre_logout(user, payload.get("iat"))` também em `_get_user_from_cookie` (page guard) e em `/auth/refresh`, com o mesmo tratamento aplicado em `get_current_user`. Adicionar teste de regressão que copie o cookie de refresh, execute logout, e verifique que tanto o refresh quanto o acesso a páginas HTML falham. O padrão do teste é análogo ao já existente em `tests/test_pentest_regression.py` para SEC-5 (revogação de access token), estendido para os dois caminhos remanescentes.

---

### SEC-19 — Base de dados e arquivo de ambiente presentes no diretório de trabalho

**Severidade:** Informativa
**Categoria:** Segurança / Higiene
**Prioridade:** Curto prazo

**Evidência**
O diretório do projeto contém `economart.db` (217 KB), `_smoke.db` e `_smoketest.db`, além de `.env` com segredos reais. Todos estão corretamente excluídos do versionamento pelo `.gitignore`, e a verificação com `git ls-files` confirma que não foram commitados.

**Impacto**
Nenhum vazamento ocorreu. O risco é operacional: arquivos de banco com dados reais em ambiente de desenvolvimento podem ser copiados inadvertidamente, incluídos em backups não controlados, ou expostos se a máquina for comprometida. Um `git add -f` acidental os incluiria no repositório.

**Recomendação**
Remover os arquivos de banco de teste não utilizados. Considerar mover a base de desenvolvimento para fora da árvore do projeto. Se houver dados reais de produção nesses arquivos, tratá-los conforme a política de dados da organização.

---

## 4. Achados — Banco de Dados

### DB-01 — Bifurcação da hash chain de auditoria sob concorrência

**Severidade:** Crítica
**Categoria:** Banco de Dados / Segurança
**Prioridade:** Imediata

**Evidência**
`app/models/audit_logs.py`, função `attach_audit_chain_listener()`. No evento `before_flush`, o código consulta a última linha de `audit_logs` ordenada por `timestamp DESC, id DESC` para obter o hash antecessor, e encadeia os novos registros a partir dele. Não há lock, nem serialização, nem restrição de unicidade sobre `prev_hash`.

**Impacto**
Com dois workers gunicorn processando requisições simultâneas, ambos leem a mesma linha como antecessora e computam hashes que apontam para o mesmo predecessor. A cadeia deixa de ser linear e se torna uma árvore. O endpoint `/api/admin/audit-logs/verify-chain`, que percorre os registros em ordem cronológica assumindo linearidade, encontrará divergência e reportará **violação de integridade permanente** — indistinguível de adulteração real. Como a cadeia não pode ser recomputada sem invalidar a premissa de imutabilidade que ela existe para garantir, o mecanismo de detecção de fraude torna-se inútil de forma irreversível. Este é o controle desenhado especificamente para detectar administrador malicioso alterando registros no banco; sua falha compromete o modelo de ameaças central do sistema.

Adicionalmente, a consulta do antecessor executa `ORDER BY timestamp DESC, id DESC LIMIT 1` a cada flush que contenha um audit log. Sem índice composto correspondente, o custo cresce com o tamanho da tabela — que é justamente a tabela que mais cresce no sistema.

**Recomendação**
Serializar a escrita da cadeia. Opções: sequência dedicada com lock de advisory no PostgreSQL para garantir ordem total; ou tabela separada mantendo o ponteiro do último hash, atualizada com lock de linha; ou processar audit logs por um único produtor via fila, desacoplando da requisição. Criar índice composto sobre as colunas de ordenação. Verificar se a cadeia já bifurcou no ambiente atual — se o `verify-chain` reporta falha hoje, é necessário decidir entre reinicializar a cadeia com marco documentado ou reconstruí-la.

---

### DB-02 — Migrações sem versionamento nem controle de concorrência

**Severidade:** Alta
**Categoria:** Banco de Dados / Infraestrutura
**Prioridade:** Curto prazo

**Evidência**
`app/migrations.py`, função `run_schema_migrations()`. Executa uma lista de 52 comandos DDL a cada inicialização da aplicação, capturando e ignorando exceções cujo texto contenha "already exists", "duplicate column" ou "duplicate object". Não há tabela de controle de versão, não há registro de quais migrações foram aplicadas, e não existe caminho de reversão.

**Impacto**
Não é possível determinar o estado de schema de um ambiente sem inspecioná-lo diretamente. Migrações que falham por motivo diferente dos três textos previstos são apenas registradas como aviso e ignoradas — a aplicação sobe com schema incompleto e falhará depois, em runtime, de forma difícil de diagnosticar. O comando `ALTER TYPE ... ADD VALUE` para enums do PostgreSQL não pode ser executado dentro de bloco transacional em versões anteriores à 12, e seu comportamento com `IF NOT EXISTS` varia entre versões. Se a plataforma escalar para múltiplas réplicas, várias instâncias executarão DDL simultaneamente sobre o mesmo banco, com resultado imprevisível. A detecção de erro por comparação de string em mensagens de exceção é frágil e quebra com mudanças de versão do driver ou localização de idioma.

**Recomendação**
Adotar Alembic. Criar uma revisão base que represente o schema atual, e migrar as alterações futuras para o fluxo versionado. Executar migrações como passo explícito do pipeline de deploy, antes de iniciar a aplicação, com lock que impeça execução concorrente. Isso também viabiliza revisão de mudanças de schema em code review e rollback controlado.

---

### DB-03 — Carregamento eager desnecessário na listagem principal

**Severidade:** Alta
**Categoria:** Banco de Dados / Performance
**Prioridade:** Imediata

**Evidência**
`app/services/invoice_service/queries.py`, função `_invoice_options()`, utilizada por padrão em `_query_visible_invoices()`. Inclui `selectinload(Invoice.approval_history).selectinload(ApprovalHistory.user)` e `selectinload(Invoice.attachments)`. A variante `_invoice_options_light()` existe e omite essas relações, mas só é ativada quando o parâmetro `fields=light` é passado — e a verificação no código do frontend confirma que **nenhum arquivo JavaScript envia esse parâmetro**.

**Impacto**
Cada requisição de listagem com `per_page=100` dispara, além da query principal, uma consulta para carregar todo o histórico de aprovação das cem notas, outra para os usuários desses históricos, e outra para os anexos. O volume de dados transferidos do banco é uma ordem de grandeza maior que o necessário para renderizar a tabela — que exibe apenas número, setor, valor, datas e status. A otimização foi implementada corretamente no backend e nunca conectada no frontend, o que significa que o custo permanece integral em produção. Com centenas de usuários navegando simultaneamente, este é o maior consumidor de recursos de banco do sistema.

**Recomendação**
Fazer o frontend solicitar o modo leve na listagem. Melhor ainda: inverter o padrão — a listagem usa carregamento mínimo por definição, e apenas o endpoint de detalhe carrega o grafo completo. Considerar projetar diretamente para um objeto de transferência contendo somente os campos exibidos, evitando materializar entidades completas.

---

### DB-04 — Cálculo de total via subconsulta sobre query completa

**Severidade:** Alta
**Categoria:** Banco de Dados / Performance
**Prioridade:** Curto prazo

**Evidência**
`app/services/invoice_service/queries.py`, função `get_invoices_for_user()`. O total monetário é calculado com `db.query(func.sum(Invoice.amount)).filter(Invoice.id.in_(query.with_entities(Invoice.id)))`, onde `query` é a consulta completa incluindo todos os filtros, joins e opções de carregamento.

**Impacto**
Gera um predicado `IN (SELECT ...)` cuja subconsulta arrasta toda a complexidade da query principal. Otimizadores frequentemente materializam esse conjunto intermediário; com dezenas de milhares de notas correspondendo ao filtro, o custo é proporcional ao total de registros, não à página exibida. Na mesma requisição já se executa `query.count()` — que percorre o mesmo conjunto — e a busca paginada. São três varreduras do mesmo predicado para produzir uma única tela. Em tabela grande, este é o ponto de maior latência do endpoint mais acessado do sistema.

**Recomendação**
Obter contagem e soma em uma única consulta agregada sobre a query filtrada, sem as opções de carregamento eager e sem a subconsulta de identificadores. Para conjuntos muito grandes, avaliar se o total precisa ser exato e em tempo real, ou se uma aproximação atualizada periodicamente atende à necessidade do usuário.

---

### DB-05 — Endpoint de alertas sem paginação, invocado em toda navegação

**Severidade:** Alta
**Categoria:** Banco de Dados / Performance
**Prioridade:** Imediata

**Evidência**
`app/services/alert_service.py`, função `get_alerts()`. Executa cinco consultas independentes — vencidas, a vencer em 72 horas, emissão antiga, reprovadas e pendentes de revisão — todas terminando em `.all()`, sem `limit`. Cada uma utiliza `_query_visible_invoices()`, que aplica o carregamento eager completo descrito em DB-03. O frontend invoca `/alerts/` dentro de `initShell()` (`app/static/js/shell.js`), executado em **toda página autenticada**.

**Impacto**
Um diretor responsável por um volume alto de notas recebe, a cada navegação entre páginas, um documento JSON contendo todas as notas de cada categoria — potencialmente milhares de registros, cada um com histórico e anexos carregados. O custo é multiplicado pelo número de páginas visitadas e pelo número de usuários ativos. Este é simultaneamente o maior consumidor de banco, de banda e de memória do servidor. Sob carga corporativa real, é o primeiro componente que derruba a aplicação. O propósito da chamada, conforme o código do frontend, é exibir um **contador numérico** em um badge de menu.

**Recomendação**
Separar contagem de listagem. O badge precisa apenas de agregações `COUNT`, obteníveis em consulta única e barata. A listagem detalhada pertence à página de alertas, com paginação. Aplicar cache de curta duração sobre as contagens, já que precisão ao segundo não é requisito para um indicador de menu.

---

### DB-06 — Condição de corrida em `mark_paid`

**Severidade:** Média
**Categoria:** Banco de Dados / Integridade
**Prioridade:** Curto prazo

**Evidência**
`app/routers/print_routes.py`, endpoint `mark_paid`. A sequência é: carregar a nota, gerar o PDF completo — operação que baixa e descriptografa todos os anexos do R2, levando segundos —, e só então verificar `if invoice.status == InvoiceStatus.APROVADO` antes de aplicar a transição. Não há lock pessimista nem verificação de versão.

**Impacto**
A janela entre leitura e escrita tem duração de segundos, tornando a colisão provável e não meramente teórica. Duplo clique no botão, ou dois operadores do financeiro processando a mesma nota, resultam em duas transições aplicadas: dois registros `MARKED_PAID` no histórico, dois registros de auditoria, e `finance_id` refletindo o segundo executor. Para um sistema que controla liberação de pagamentos, registro duplicado de lançamento é problema de conformidade contábil — a trilha de auditoria deixa de refletir a realidade.

**Recomendação**
Adquirir lock sobre a linha antes de qualquer operação custosa, ou aplicar atualização condicional que só efetive a transição se o status ainda for o esperado, verificando o número de linhas afetadas. Gerar o PDF após confirmar a transição, não antes.

---

### DB-07 — Purga de notas executada concorrentemente por todos os workers

**Severidade:** Média
**Categoria:** Banco de Dados
**Prioridade:** Curto prazo

**Evidência**
`app/migrations.py`, função `purge_old_rejected_on_startup()`, invocada em `app/main.py` durante a inicialização. Com `--preload` a chamada ocorre uma vez no processo mestre — mas o comportamento depende de detalhe de configuração do gunicorn que não está documentado nem testado.

**Impacto**
Se a flag `--preload` for removida, se a plataforma alterar o modelo de inicialização, ou se réplicas adicionais forem provisionadas, múltiplos processos executarão simultaneamente a mesma operação de exclusão em massa — incluindo remoção de arquivos no R2. Exclusões concorrentes sobre o mesmo conjunto geram erros de chave estrangeira e deixam arquivos órfãos no armazenamento. A operação também roda no caminho crítico de inicialização: com volume alto de notas elegíveis, atrasa o startup e pode fazer o healthcheck expirar durante deploy.

**Recomendação**
Extrair a purga do ciclo de inicialização e transformá-la em tarefa agendada com lock distribuído garantindo execução única. Processar em lotes para limitar o tempo de transação.

---

### DB-08 — Índices ausentes para os padrões de consulta reais

**Severidade:** Média
**Categoria:** Banco de Dados / Performance
**Prioridade:** Curto prazo

**Evidência**
`app/migrations.py` cria índices de coluna única sobre `status`, `created_by_id`, `manager_id`, `director_id`, `invoice_number` e `supplier_document`. As consultas efetivamente executadas combinam colunas: `alert_service` filtra por `status IN (...) AND due_date < ...`; `_query_visible_invoices` filtra por papel e status simultaneamente; `invoice_comments` é consultada por `invoice_id` sem índice declarado; `audit_logs` é ordenada por `timestamp DESC, id DESC` a cada inserção.

**Impacto**
O planejador usará um índice de coluna única e filtrará o restante em memória, ou optará por varredura sequencial quando a seletividade for baixa. Com dezenas de milhares de notas, as consultas de alerta — as mais frequentes do sistema — degradam progressivamente. A ausência de índice em `invoice_comments.invoice_id` afeta tanto a listagem de comentários quanto a contagem agregada usada na listagem principal.

**Recomendação**
Analisar os planos de execução das consultas mais frequentes em volume representativo e criar índices compostos correspondentes, respeitando a ordem de seletividade. Priorizar: status combinado com data de vencimento, identificador de comentário por nota, e o par de ordenação dos audit logs.

---

### DB-09 — Ausência de tratamento transacional explícito nos fluxos de estado

**Severidade:** Média
**Categoria:** Banco de Dados / Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
`app/services/invoice_service/fsm.py`. Funções como `manager_review` e `director_review` executam múltiplas mutações — alteração de status, gravação de timestamps, inserção de histórico, inserção de auditoria — seguidas de `db.commit()`. Não há bloco de tratamento de exceção com rollback explícito. As notificações por e-mail são invocadas antes do commit em alguns caminhos.

**Impacto**
A sessão do SQLAlchemy é encerrada pela dependência `get_db`, que executa apenas `close()` — sem rollback explícito. Uma exceção entre as mutações e o commit deixa a sessão em estado indefinido; o comportamento depende de detalhes de implementação do driver. Em caminhos onde a notificação precede o commit, é possível enviar e-mail informando aprovação que subsequentemente falha ao persistir — o aprovador recebe confirmação de uma ação que não ocorreu.

**Recomendação**
Envolver as operações de mutação em contexto transacional explícito com rollback garantido em caso de falha. Mover efeitos colaterais externos — envio de e-mail, chamadas a serviços — para depois do commit bem-sucedido, ou registrá-los na mesma transação através da fila persistente que já existe.

---

### DB-10 — Ausência de restrição de unicidade em `invoice_number`

**Severidade:** Baixa
**Categoria:** Banco de Dados
**Prioridade:** Longo prazo

**Evidência**
`app/models/invoices.py`. A coluna não possui restrição de unicidade. A detecção de duplicidade é feita em código (`_check_duplicate_invoice_number`), com possibilidade de sobreposição via parâmetro `confirm_duplicate`.

**Impacto**
A decisão é documentada e justificada — fornecedores distintos legitimamente reutilizam numeração no Brasil, e uma restrição simples quebraria dados históricos. O risco residual é a ausência de qualquer garantia no nível de armazenamento: uma condição de corrida entre duas submissões simultâneas contorna a verificação em aplicação, e um defeito futuro no código de detecção não encontra rede de proteção.

**Recomendação**
Avaliar restrição parcial de unicidade sobre a combinação de documento do fornecedor e número da nota, restrita aos status ativos. Isso preserva o caso de uso legítimo enquanto oferece garantia estrutural.

---

## 5. Achados — Backend

### BE-01 — Supressão silenciosa de exceções em 35 pontos do código

**Severidade:** Alta
**Categoria:** Backend / Confiabilidade
**Prioridade:** Curto prazo

**Evidência**
Trinta e cinco ocorrências de `except Exception` distribuídas pelo código, das quais a maioria executa `pass` ou apenas registra em log e prossegue. Casos representativos: `app/services/invoice_service/fsm.py` na exclusão de arquivos do R2; `app/services/email_service.py` no envio; `app/routers/pending_actions.py` nas notificações; `app/services/pdf_service.py` na concatenação de anexos.

**Impacto**
Falhas reais tornam-se invisíveis. A exclusão de arquivo no R2 que falha silenciosamente acumula objetos órfãos indefinidamente — custo de armazenamento crescente e, mais grave, retenção de documentos que deveriam ter sido eliminados, com implicações de conformidade. A concatenação de anexos que ignora falhas produz um comprovante oficial **sem os documentos que deveria conter**, sem qualquer indicação de que algo faltou — o financeiro aprova pagamento baseado em documento incompleto. A ausência de sinalização impede tanto a detecção quanto a correção.

**Recomendação**
Classificar cada supressão: as que são genuinamente recuperáveis devem registrar em nível apropriado com contexto suficiente para diagnóstico; as que mascaram falhas relevantes devem propagar. Para operações cuja falha compromete a integridade do resultado — como a montagem do comprovante — sinalizar explicitamente ao usuário que o documento está incompleto. Restringir a captura ao tipo de exceção esperado em vez de `Exception` genérico.

---

### BE-02 — Ausência de timeout de requisição

**Severidade:** Alta
**Categoria:** Backend / Confiabilidade
**Prioridade:** Curto prazo

**Evidência**
Nem o `Procfile` nem o `railway.toml` configuram limite de tempo para processamento de requisição. O `gunicorn` é iniciado com dois workers e sem `--timeout` explícito.

**Impacto**
Uma requisição de geração de comprovante que baixa cinco anexos de dez megabytes cada, descriptografa e concatena, pode ocupar um worker por dezenas de segundos. Com apenas dois workers, duas requisições dessas simultâneas tornam a aplicação inteira indisponível — inclusive para o healthcheck, o que pode disparar reinicialização em cascata. Não há mecanismo que interrompa o processamento; o worker permanece ocupado até concluir ou falhar.

**Recomendação**
Definir timeout explícito no servidor de aplicação, dimensionado para abortar requisições anômalas sem afetar as legítimas. Mover operações inerentemente lentas — geração de PDF com múltiplos anexos — para processamento assíncrono, retornando ao usuário um identificador de acompanhamento.

---

### BE-03 — Endpoint duplicado com comportamentos divergentes

**Severidade:** Alta
**Categoria:** Backend / Arquitetura
**Prioridade:** Curto prazo

**Evidência**
`POST /api/invoices/{invoice_id}/mark-paid` é registrado duas vezes: em `app/routers/print_routes.py` (linha 124) e em `app/routers/invoices_fsm.py` (linha 126). A ordem de inclusão em `app/main.py` registra `print_routes` na linha 244 e `invoices` na linha 246 — o primeiro registro prevalece.

**Impacto**
A implementação de `invoices_fsm.py` é código morto: nunca executa. Os dois comportamentos diferem substancialmente — a versão ativa retorna um PDF binário e é idempotente para notas já pagas; a versão inativa retorna JSON e delega ao serviço de domínio, que valida a transição estritamente. Um desenvolvedor lendo `invoices_fsm.py` concluirá que a rota se comporta de uma forma quando na prática se comporta de outra. Uma reordenação inadvertida das inclusões de router — durante refatoração, por exemplo — altera silenciosamente o contrato da API: clientes que esperam PDF passariam a receber JSON. A suíte de testes atual não detecta a duplicação.

**Recomendação**
Remover a implementação inativa. Documentar no código remanescente por que a rota de lançamento reside no módulo de impressão. Adicionar verificação automatizada que detecte rotas duplicadas na inicialização.

---

### BE-04 — Worker assíncrono com gerenciamento frágil de loop de eventos

**Severidade:** Média
**Categoria:** Backend / Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
`app/services/email_queue_service.py`, função `start_background_worker()`. Utiliza `asyncio.get_event_loop()` — depreciado desde Python 3.10 quando não há loop em execução — com fallback para criação de novo loop. O worker é iniciado a partir de um handler `@app.on_event("startup")`, também depreciado.

**Impacto**
O comportamento depende de detalhes da interação entre gunicorn, o worker uvicorn e o modelo de fork. Se o loop obtido não for o que efetivamente processa as requisições, a tarefa nunca executa e a fila de e-mails cresce indefinidamente sem qualquer alerta — códigos de redefinição de senha e notificações de aprovação simplesmente não são entregues. A falha é silenciosa: nenhum erro é registrado, apenas ausência de processamento. Não há monitoramento do tamanho da fila que permitisse detectar a situação.

**Recomendação**
Migrar para o gerenciador de ciclo de vida moderno do FastAPI, que fornece contexto assíncrono garantido. Adicionar métrica de profundidade da fila e alerta quando mensagens permanecerem pendentes além de um limite. Considerar processo worker dedicado, separado do servidor web, para isolamento e escalabilidade independente.

---

### BE-05 — Ausência de circuit breaker para dependências externas

**Severidade:** Média
**Categoria:** Backend / Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
Chamadas a serviços externos — R2 via boto3 (`app/services/drive_service.py`), API de CNPJ (`app/services/document_service.py`), Resend e SMTP (`app/services/email_service.py`) — não possuem mecanismo de interrupção após falhas sucessivas. O boto3 está configurado com três tentativas de retry.

**Impacto**
Durante indisponibilidade do R2, cada upload consome o tempo de três tentativas com backoff antes de falhar, multiplicando a latência e ocupando workers. O comportamento amplifica a falha em vez de degradá-la graciosamente: quanto mais usuários tentam, mais recursos são consumidos em operações destinadas a falhar. Com apenas dois workers, a saturação é rápida.

**Recomendação**
Implementar circuit breaker que, após sequência de falhas, passe a rejeitar chamadas imediatamente por um período, com tentativas periódicas de restabelecimento. Comunicar ao usuário de forma clara que o serviço está temporariamente indisponível, em vez de fazê-lo aguardar por um erro previsível.

---

### BE-06 — Ausência de chave de idempotência em operações de mutação

**Severidade:** Média
**Categoria:** Backend / Integridade
**Prioridade:** Médio prazo

**Evidência**
Nenhum endpoint de mutação aceita identificador de idempotência. Operações como criação de nota, submissão, aprovação e lançamento dependem exclusivamente da validação de estado para prevenir duplicação.

**Impacto**
Requisições reenviadas — por instabilidade de rede, duplo clique, ou retry automático de cliente — podem produzir efeitos duplicados. A criação de nota é o caso mais visível: nada impede que a mesma nota seja criada duas vezes, gerando duplicidade que só será detectada no momento da submissão, e ainda assim de forma contornável.

**Recomendação**
Aceitar cabeçalho de idempotência nas operações de criação e transição, registrando as chaves processadas com janela de retenção adequada. Requisições repetidas com a mesma chave retornam o resultado original sem reexecutar o efeito.

---

### BE-07 — Camada de domínio acoplada ao framework web

**Severidade:** Média
**Categoria:** Backend / Arquitetura
**Prioridade:** Longo prazo

**Evidência**
`app/services/invoice_service/` — que representa a camada de regras de negócio — importa e lança `fastapi.HTTPException` diretamente. O mesmo ocorre em `app/services/document_service.py` e nos módulos compartilhados de admin.

**Impacto**
A lógica de negócio torna-se inutilizável fora do contexto HTTP. Um processo em lote, uma tarefa agendada, uma interface de linha de comando ou um consumidor de fila que precise executar a mesma regra receberá exceções de framework web que não sabe tratar. Códigos de status HTTP são detalhe de apresentação incorporado à camada de domínio. Testes unitários da regra de negócio precisam importar o framework inteiro.

**Recomendação**
Definir exceções próprias do domínio, expressando as condições de negócio — nota em estado inválido, permissão insuficiente, duplicidade detectada. Traduzir para códigos HTTP na camada de roteamento, através de manipuladores de exceção. Esta é uma refatoração incremental que pode acompanhar a evolução natural do código.

---

### BE-08 — Ausência de validação de tamanho na concatenação de PDFs

**Severidade:** Média
**Categoria:** Backend / Disponibilidade
**Prioridade:** Curto prazo

**Evidência**
`app/services/pdf_service.py`, função `generate_print_pdf()`, e `app/routers/invoices_attachments.py`, endpoint `get_attachment_merged`. Ambos iteram sobre todas as páginas de todos os anexos, adicionando-as a um documento em memória. Não há limite de páginas nem de tamanho do resultado.

**Impacto**
Cinco arquivos de dez megabytes com alta densidade de páginas produzem um documento cuja construção consome memória várias vezes superior ao tamanho dos arquivos originais — o pypdf mantém estruturas intermediárias. A operação ocorre inteiramente em memória, sem streaming. Com múltiplas requisições simultâneas, o consumo pode exceder o limite do contêiner e causar terminação abrupta do processo. Bibliotecas de manipulação de PDF também são alvo histórico de documentos maliciosos construídos para provocar consumo desproporcional de recursos.

**Recomendação**
Estabelecer limite de páginas no documento resultante, rejeitando ou truncando com aviso quando excedido. Processar de forma incremental quando possível. Considerar gerar o comprovante de forma assíncrona e armazená-lo, servindo-o subsequentemente como arquivo estático.

---

## 6. Achados — Arquitetura

### ARQ-01 — Dependência circular entre módulo principal e roteadores

**Severidade:** Alta
**Categoria:** Arquitetura
**Prioridade:** Médio prazo

**Evidência**
`app/routers/print_routes.py` e `app/routers/pages.py` executam `from app.main import templates` no nível do módulo. `app/main.py` importa esses mesmos roteadores. `app/security/page_auth.py` realiza o mesmo import dentro do corpo de uma função, com comentário explicando que a localização visa evitar o ciclo.

**Impacto**
A aplicação só inicializa porque a ordem de execução dos imports acontece de forma favorável. Qualquer reorganização — mover uma declaração, adicionar um import, alterar a ordem de inclusão dos roteadores — pode produzir erro de importação circular em tempo de inicialização. A necessidade de importar dentro de funções para contornar o problema é sintoma reconhecido de fronteiras mal definidas entre módulos. Testar um roteador isoladamente exige carregar a aplicação inteira.

**Recomendação**
Extrair a configuração de templates para um módulo próprio, sem dependências da aplicação. Os roteadores passam a importar desse módulo neutro, eliminando o ciclo. Aplicar o mesmo princípio a outros recursos compartilhados que hoje residem no módulo principal.

---

### ARQ-02 — Módulo principal acumula responsabilidades heterogêneas

**Severidade:** Média
**Categoria:** Arquitetura
**Prioridade:** Médio prazo

**Evidência**
`app/main.py`, com 256 linhas após refatoração recente, ainda concentra: cálculo de versão de assets estáticos, instanciação da aplicação, tratamento de falha de segredos na inicialização, definição de classe customizada para servir arquivos estáticos, configuração de cinco middlewares, política de CORS, orquestração de migrações, inicialização do worker de e-mail e inclusão de oito roteadores.

**Impacto**
Alterações não relacionadas convergem para o mesmo arquivo, elevando probabilidade de conflito em trabalho paralelo. A configuração da aplicação está entrelaçada com a lógica de inicialização, dificultando a criação de instâncias com configuração alternativa para testes. A ordem dos middlewares — que é semanticamente relevante — está implícita na sequência das chamadas, documentada apenas por comentário.

**Recomendação**
Adotar o padrão de fábrica de aplicação, com funções dedicadas para configuração de middlewares, registro de roteadores e inicialização de recursos. Isso viabiliza instanciar a aplicação com configurações distintas e torna explícita a ordem de composição.

---

### ARQ-03 — Ausência de camada de transferência de dados

**Severidade:** Média
**Categoria:** Arquitetura
**Prioridade:** Longo prazo

**Evidência**
As entidades do SQLAlchemy trafegam da camada de persistência até a serialização de resposta. `app/routers/invoices_helpers.py`, função `invoice_response()`, converte a entidade em modelo Pydantic acessando relacionamentos diretamente, o que dispara carregamento sob demanda quando a relação não foi previamente carregada.

**Impacto**
Alterações no schema do banco propagam-se até o contrato da API. Consultas otimizadas não podem ser expressas — é sempre a entidade completa. A dependência de carregamento eager configurado corretamente torna o desempenho frágil: um caminho de código que esqueça a opção adequada introduz consultas adicionais silenciosamente. Este é precisamente o mecanismo por trás dos achados DB-03 e DB-04.

**Recomendação**
Introduzir objetos de transferência para os casos de uso de maior volume, projetando diretamente as colunas necessárias na consulta. Isso desacopla o contrato externo do schema interno e torna o custo de cada consulta explícito e controlável.

---

### ARQ-04 — Regra de autorização duplicada em múltiplos pontos

**Severidade:** Média
**Categoria:** Arquitetura / Segurança
**Prioridade:** Médio prazo

**Evidência**
A determinação de quem pode visualizar uma nota está implementada em pelo menos três locais com lógicas independentes: `_can_view()` em `app/services/invoice_service/queries.py`, `_user_has_invoice_access()` em `app/routers/print_routes.py`, e `_query_visible_invoices()` no mesmo módulo de queries. As três definições divergem — a versão de `print_routes` concede acesso a `CONTAS_A_PAGAR` e contém comentário obsoleto indicando que o papel "será incluído na Fase 3", quando já foi.

**Impacto**
Divergência entre implementações produz inconsistência de autorização: um usuário pode ter acesso negado por um caminho e concedido por outro. Alterações na política de acesso exigem localizar e atualizar todas as cópias — omissão de qualquer uma cria brecha. Como se trata de controle de acesso a dados financeiros, a duplicação é risco de segurança, não apenas de manutenção.

**Recomendação**
Consolidar em uma única definição autoritativa, com as demais delegando a ela. Cobrir a política consolidada com testes que exercitem a matriz completa de papéis e relações.

---

### ARQ-05 — Concentração excessiva em módulos de helpers

**Severidade:** Baixa
**Categoria:** Arquitetura / Qualidade
**Prioridade:** Longo prazo

**Evidência**
Após a refatoração, `app/routers/invoices_helpers.py` contém 405 linhas agregando responsabilidades distintas: conversão de exceções de validação, extração de dados do cliente, cálculo de alertas de negócio, cache de contagem via variável de contexto, serialização de resposta, validação de segurança de PDF e definição de modelos de requisição. `app/routers/admin_users.py` mantém 449 linhas, com a função `update_user` ocupando cerca de 150.

**Impacto**
Módulos de helpers tendem a crescer indefinidamente por serem o destino natural de código que não pertence claramente a outro lugar. A concentração de responsabilidades não relacionadas dificulta a localização de código e amplia o escopo de cada alteração. A função `update_user` mistura oito verificações distintas de autorização com a aplicação das mudanças, resultando em complexidade ciclomática elevada.

**Recomendação**
Separar os helpers por afinidade — validação de arquivos, serialização, regras de alerta — em módulos coesos. Extrair as verificações de `update_user` para funções nomeadas que expressem cada regra, tornando-as individualmente testáveis.

---

## 7. Achados — Frontend

### FE-01 — Carregamento integral de dezenove scripts em todas as páginas

**Severidade:** Alta
**Categoria:** Frontend / Performance
**Prioridade:** Curto prazo

**Evidência**
`app/templates/base.html` inclui dezenove arquivos JavaScript de forma incondicional. A página de login (`app/templates/login.html`) carrega seis. Entre os scripts carregados em toda página autenticada estão `admin-users.js`, `admin-departments.js`, `admin-audit.js`, `finance.js`, `review.js` e `drawer.js` — cada um relevante para um papel ou tela específica.

**Impacto**
Aproximadamente 180 KB de JavaScript não comprimido e dezenove requisições HTTP por carregamento de página. Um funcionário comum baixa e executa todo o código administrativo, que nunca utilizará. Em conexões móveis ou de alta latência, o impacto na experiência é significativo. Cada script é uma função autoexecutável que registra ouvintes de eventos e manipula o namespace global no momento do carregamento — trabalho desperdiçado. A ausência de empacotamento também significa que qualquer alteração em um arquivo invalida o cache apenas dele, mas o parâmetro de versão é compartilhado, invalidando todos.

**Recomendação**
Carregar condicionalmente por página, aproveitando o bloco de scripts já existente nos templates. Alternativamente, adotar módulos ES nativos com importação dinâmica, mantendo a ausência de etapa de build. A restrição de "sem build" é uma decisão arquitetural válida, mas não impede carregamento seletivo.

---

### FE-02 — Segurança contra XSS dependente de disciplina manual

**Severidade:** Média
**Categoria:** Frontend / Segurança
**Prioridade:** Médio prazo

**Evidência**
O padrão predominante nos módulos JavaScript é a construção de HTML via template strings atribuídas a `innerHTML`, com escape manual através da função `escapeHtml()`. Ocorre em `invoices-list.js`, `drawer.js`, `admin-users.js`, `invoice-detail.js` e outros. Valores originados de entrada de usuário — nome de fornecedor, descrição, comentários — são armazenados sem sanitização no servidor.

**Impacto**
A segurança depende de o desenvolvedor lembrar de aplicar o escape em cada interpolação. Uma única omissão em qualquer um dos módulos cria vulnerabilidade de XSS armazenado. Considerando que valores como `supplier_name` aceitam conteúdo arbitrário e são renderizados em múltiplos contextos — lista, drawer, detalhe, PDF —, a superfície é ampla. A CSP sem `unsafe-inline` para scripts limita o impacto de uma exploração bem-sucedida, mas não previne a injeção.

**Recomendação**
Migrar a construção de conteúdo dinâmico para APIs que não interpretam HTML, atribuindo texto através de propriedades apropriadas. Onde a estrutura HTML for necessária, montar elementos programaticamente. Considerar verificação automatizada que sinalize atribuições a `innerHTML` com interpolação não escapada.

---

### FE-03 — Versionamento de assets baseado em metadados de arquivo

**Severidade:** Baixa
**Categoria:** Frontend / Performance
**Prioridade:** Médio prazo

**Evidência**
`app/main.py`, função `_compute_static_version()`. Calcula um hash a partir do nome, timestamp de modificação e tamanho de oito arquivos selecionados — não do conteúdo, e não de todos os arquivos servidos.

**Impacto**
Uma nova cópia do repositório altera os timestamps de todos os arquivos, invalidando o cache de todos os usuários mesmo sem mudança de conteúdo. Inversamente, uma alteração em arquivo não incluído na lista — `drawer.js`, por exemplo, ou qualquer CSS de página — não altera a versão, e os usuários continuam recebendo a versão em cache. Como o cabeçalho de cache é de 24 horas, uma correção pode levar um dia para alcançar os usuários.

**Recomendação**
Calcular o identificador a partir do conteúdo dos arquivos, cobrindo todos os assets servidos. Idealmente, incorporar o hash ao nome do arquivo, permitindo cache imutável de longa duração.

---

### FE-04 — Comentários e referências desatualizados no código cliente

**Severidade:** Baixa
**Categoria:** Frontend / Qualidade
**Prioridade:** Longo prazo

**Evidência**
`app/routers/print_routes.py`, docstring do endpoint `/verify/{id}`, afirma que "o JS detecta sessão autenticada (`localStorage.access_token`)". O armazenamento do token em `localStorage` foi eliminado — o código atual utiliza `window.Auth` com token em memória. Comentários referenciando "Fase 3", "P0", "P1", "P2" e itens de auditorias anteriores permanecem distribuídos pelo código.

**Impacto**
Documentação incorreta induz a conclusões erradas. Um desenvolvedor auditando o fluxo de autenticação com base nesse comentário procuraria uma vulnerabilidade que não existe, ou pior, assumiria um comportamento incorreto ao modificar o código. Referências a fases de projeto perdem significado com o tempo.

**Recomendação**
Atualizar os comentários divergentes. Substituir referências a fases por descrições do comportamento ou por links para a documentação de decisões arquiteturais.

---

### FE-05 — `/verify/{id}` não revela detalhes completos após login **[novo — Manus]**

**Severidade:** Alta
**Categoria:** Frontend / Contrato de UX
**Prioridade:** Curto prazo

**Evidência**
`app/templates/verify.html:113` carrega exclusivamente `<script src="/static/js/verify.js" defer>`. Nenhum outro módulo é incluído. O comportamento pretendido — detectado ao ler `verify.js` e a docstring do endpoint em `print_routes.py` — é: página renderiza mascarada, e se o visitante estiver autenticado o JavaScript detecta `window.Auth` e chama `/api/invoices/{id}/verify-full` para revelar. Mas `window.Auth` é definido em `core-auth.js`, que não é carregado por este template.

**Impacto**
A promessa documentada de "participante autorizado vê banner completo após login" não é cumprida. Um diretor que escaneie o QR code do próprio comprovante e já esteja logado no sistema vê o mesmo conteúdo mascarado que um visitante anônimo. A funcionalidade existe no backend (`/verify-full` retorna dados completos com controle de acesso correto), mas está desconectada do frontend. Como a página de verify é o único mecanismo público de conferência de autenticidade, essa desconexão reduz o valor prático do QR code impresso.

**Recomendação**
Incluir `core-auth.js` no template de verify (com dependências mínimas — `core-api.js` também é necessário para `apiFetch`). Alternativamente, autenticar via cookie no endpoint `/verify-full`, eliminando a dependência de bootstrapping de token na página pública. Adicionar teste automatizado — mesmo que via `TestClient` simulando o fluxo — que valide que o endpoint retorna dados extras para usuário autenticado.

---

### FE-06 — Atalhos de teclado `g i` e `g a` não funcionam **[novo — Manus]**

**Severidade:** Baixa
**Categoria:** Frontend / UX
**Prioridade:** Longo prazo

**Evidência**
A auditoria dinâmica reproduziu que `?`, `Esc` e `n` funcionam, mas as sequências `g i` (ir para notas) e `g a` (ir para alertas) não navegam apesar de aparecerem no cheatsheet do próprio sistema.

**Impacto**
Baixo. Atalhos de teclado avançados são conveniência para usuários intensos; a navegação por menu continua funcionando. O problema é de credibilidade — o cheatsheet promete algo que não entrega, indicando que a máquina de estados do dispatcher regrediu em algum ponto sem que ninguém percebesse.

**Recomendação**
Reproduzir localmente para confirmar a máquina de estados do listener de teclado. Adicionar smoke automatizado por atalho — o custo é baixo e evita regressões futuras nesta camada.

---

### FE-07 — Colagem de labels/iniciais na tabela administrativa **[novo — Manus]**

**Severidade:** Baixa
**Categoria:** Frontend / Acessibilidade
**Prioridade:** Longo prazo

**Evidência**
A auditoria dinâmica extraiu texto da tabela de usuários e encontrou padrões como `AAdministrador` e `CAPContas a Pagar`. Isso sugere que ícones ou badges com iniciais são renderizados como texto adjacente ao rótulo completo, sem separação semântica.

**Impacto**
Baixo para uso visual; relevante para leitores de tela e para qualquer processamento automático da página. Um usuário com deficiência visual ouve o rótulo duplicado. A extração para automação (testes, scraping legítimo, exportação) resulta em dados sujos.

**Recomendação**
Marcar ícones decorativos com `aria-hidden="true"` e garantir que o texto do badge não seja lido em duplicidade. Revisar componentes similares em outras tabelas.

---

## 7-B. Achados — Contratos e Configuração (novos)

### API-01 — Documentação da API divergente das rotas efetivas **[novo — Manus]**

**Severidade:** Média
**Categoria:** Contrato / Documentação
**Prioridade:** Curto prazo

**Evidência**
`docs/api-reference.md` documenta caminhos e métodos que não existem no código. Exemplos identificados pela auditoria dinâmica: `/review` documentado quando a rota real é `/manager-review`; `/cancel` e `/confirm` documentados quando a implementação usa `/veto`; `PUT` documentado quando o método real é `PATCH`; `/attachments` (plural) documentado quando a rota é `/attachment` (singular). A documentação de testes menciona 21 testes; a suíte real tem 106.

**Impacto**
Integração externa quebra silenciosamente. Um cliente que consuma a API seguindo a documentação recebe 404 ou 405 nos endpoints. Novos desenvolvedores do projeto formam modelo mental incorreto ao ler a documentação. Divergência entre documentação e realidade é sinal de que o processo de mudança não inclui atualização da doc — o problema se acumula.

**Recomendação**
Estabelecer a implementação como fonte canônica. Gerar a referência de API a partir do próprio FastAPI (`/openapi.json` já expõe o schema real). Adicionar teste no CI que compare todos os pares método/caminho documentados manualmente com `app.routes` e falhe em divergência. Atualizar os números da suíte de testes na documentação e considerar automatizar isso também.

---

### APP-01 — Criação de nota em DEV sem `MASTER_ENCRYPTION_KEY` retorna HTTP 500 **[novo — Manus]**

**Severidade:** Alta
**Categoria:** Configuração / Confiabilidade
**Prioridade:** Curto prazo

**Evidência**
`app/config.py:14` define `MASTER_ENCRYPTION_KEY: str = ""` (padrão vazio). `app/config.py:97` emite apenas warning em DEV informando que "PDFs não serão criptografados nesta instância local". Contudo, `app/services/drive_service.py:35` no `_master_key()` executa `raise ValueError` quando a chave é vazia, e essa exceção não é tratada nos caminhos de upload. Resultado: o warning promete fallback sem criptografia, mas o código não implementa esse fallback — qualquer criação de nota em DEV sem chave termina em HTTP 500.

**Impacto**
Onboarding quebrado. Um desenvolvedor que siga o `getting-started.md` sem gerar chave (o passo é opcional em DEV segundo o warning) consegue subir a aplicação, fazer login, navegar, mas trava no primeiro upload — com stack trace genérico no log. A mensagem de erro na UI é "erro inesperado", não indicando que basta configurar uma variável. O tempo perdido em diagnóstico é significativo, e a experiência inicial com o projeto é ruim.

**Recomendação**
Decidir explicitamente entre dois modelos: (a) tornar `MASTER_ENCRYPTION_KEY` obrigatório mesmo em DEV — `startup_security_failure()` recusa subir sem ela — com script de bootstrap que gere e escreva no `.env`; ou (b) implementar de fato o fallback sem criptografia em DEV, gravando o PDF em claro no `uploads/` com aviso explícito na UI e no log. A escolha (a) é mais segura e alinhada com a intenção original; a escolha (b) prioriza fricção baixa de onboarding.

---

## 8. Achados — Infraestrutura

### INFRA-01 — Ausência total de pipeline de integração contínua

**Severidade:** Crítica
**Categoria:** Infraestrutura
**Prioridade:** Imediata

**Evidência**
Não existe diretório `.github/workflows` nem qualquer configuração equivalente de CI. A suíte de 106 testes é executada apenas por invocação manual. O `railway.toml` realiza deploy diretamente a partir do branch principal.

**Impacto**
Nenhuma barreira entre código com defeito e produção. Um commit que quebre os testes é implantado normalmente. O histórico recente evidencia o risco: seis refatorações estruturais de grande porte foram realizadas em sequência, com validação dependente de execução manual dos testes e verificação por requisições manuais. Uma dessas refatorações introduziu duplicação de rota (BE-03) que a suíte não detecta. Sem CI, a qualidade depende inteiramente da disciplina individual, e o conhecimento sobre como validar reside na memória de quem fez.

O risco se amplia com o crescimento da equipe: um novo desenvolvedor não tem como saber que precisa executar os testes, nem quais verificações adicionais são esperadas.

**Recomendação**
Estabelecer pipeline que execute, a cada alteração proposta: a suíte completa de testes, verificação de sintaxe dos módulos JavaScript, e análise estática de segurança das dependências. Bloquear a integração enquanto houver falha. Automatizar o deploy a partir do branch principal apenas após aprovação do pipeline. Adicionar verificação de vulnerabilidades conhecidas nas dependências, hoje inexistente.

---

### INFRA-02 — Healthcheck configurado não verifica dependências

**Severidade:** Alta
**Categoria:** Infraestrutura / Confiabilidade
**Prioridade:** Imediata

**Evidência**
`railway.toml` define `healthcheckPath = "/health"`. O endpoint correspondente em `app/health.py` retorna `{"status": "ok"}` incondicionalmente, sem verificar qualquer dependência. Existe um endpoint `/health/ready` que executa verificação real do banco de dados, mas não é o configurado.

**Impacto**
O orquestrador considera saudável qualquer instância cujo processo esteja em execução. Uma aplicação com banco de dados inacessível, incapaz de atender qualquer requisição funcional, permanece recebendo tráfego indefinidamente. Durante uma indisponibilidade parcial do banco, requisições continuam sendo direcionadas a instâncias que só podem retornar erro. O mecanismo de recuperação automática da plataforma — reiniciar instâncias não saudáveis — nunca é acionado, pois nenhuma instância jamais é reportada como não saudável.

**Recomendação**
Apontar o healthcheck da plataforma para o endpoint que verifica dependências. Manter o endpoint trivial para verificação de vitalidade do processo, se a plataforma distinguir os dois conceitos. Ajustar os limites de tempo e tolerância para evitar remoção prematura durante instabilidades transitórias.

---

### INFRA-03 — Observabilidade limitada a logs em saída padrão

**Severidade:** Alta
**Categoria:** Infraestrutura
**Prioridade:** Curto prazo

**Evidência**
A instrumentação existente consiste em identificador de requisição propagado por contexto e registro de requisições que excedam 200 milissegundos ou retornem erro (`app/middleware/observability.py`). Não há integração com serviço de rastreamento de erros, coleta de métricas, alertas ou rastreamento distribuído.

**Impacto**
Erros em produção só são descobertos quando um usuário reporta. Não há visibilidade sobre taxa de erro, latência percentilada, saturação de recursos ou profundidade da fila de e-mails. Diagnosticar um incidente exige buscar manualmente nos logs da plataforma, sem agregação nem correlação. Degradação gradual — consultas que ficam progressivamente mais lentas conforme a base cresce — permanece invisível até tornar-se falha completa. Para um sistema que processa aprovações financeiras, a ausência de alerta significa que uma indisponibilidade pode durar horas antes de ser notada.

**Recomendação**
Integrar serviço de captura de exceções com notificação. Expor métricas fundamentais — taxa de requisições, taxa de erro, distribuição de latência, saturação — e configurar alertas sobre elas. Instrumentar indicadores específicos do domínio: tamanho da fila de e-mails, idade da mensagem mais antiga pendente, taxa de falha em uploads.

---

### INFRA-04 — Estratégia de backup não verificada

**Severidade:** Alta
**Categoria:** Infraestrutura / Continuidade
**Prioridade:** Curto prazo

**Evidência**
Não há configuração de backup no repositório. A documentação menciona dependência do backup automático da plataforma. O armazenamento de objetos no R2 não possui versionamento habilitado. Não existe procedimento documentado de recuperação.

**Impacto**
Backup não testado é hipótese, não garantia. Não se sabe o objetivo de ponto de recuperação — quanto de dado se perderia — nem o objetivo de tempo de recuperação. Os PDFs no R2 não têm proteção contra exclusão acidental ou maliciosa: a operação de purga automática exclui arquivos permanentemente, e um defeito nessa lógica destrói documentos fiscais cuja retenção é obrigatória por cinco anos. A base de dados e os documentos residem no mesmo provedor, sem cópia independente.

**Recomendação**
Documentar e testar o procedimento de restauração, medindo o tempo real necessário. Habilitar versionamento no armazenamento de objetos. Estabelecer cópia em provedor distinto para os dados sujeitos a retenção legal. Definir formalmente os objetivos de ponto e tempo de recuperação, validando-os em exercício periódico.

---

### INFRA-05 — Número de workers fixo e insuficiente

**Severidade:** Alta
**Categoria:** Infraestrutura / Escalabilidade
**Prioridade:** Curto prazo

**Evidência**
`Procfile` e `railway.toml` especificam `-w 2`, valor fixo independente dos recursos disponíveis na instância.

**Impacto**
Se a instância dispuser de mais núcleos, permanecem ociosos. Considerando que operações como geração de PDF são intensivas em CPU e bloqueantes, dois workers significam que duas requisições pesadas simultâneas esgotam a capacidade — incluindo para o healthcheck e para requisições triviais. Com milhares de usuários, dois workers são insuficientes por ordens de magnitude. Não há configuração de conexões máximas do pool de banco alinhada ao número de workers, o que pode levar a esgotamento de conexões ao escalar.

**Recomendação**
Derivar o número de workers dos recursos disponíveis, tornando-o configurável por variável de ambiente. Dimensionar o pool de conexões do banco considerando o produto de workers por instâncias. Realizar teste de carga para determinar a configuração adequada ao perfil de tráfego esperado.

---

### INFRA-06 — Ausência de containerização

**Severidade:** Média
**Categoria:** Infraestrutura
**Prioridade:** Médio prazo

**Evidência**
Não há `Dockerfile` nem configuração equivalente. O build utiliza nixpacks, mecanismo automático da plataforma que infere o ambiente a partir dos arquivos do projeto.

**Impacto**
O ambiente de execução não é reproduzível localmente nem versionado. Uma atualização do nixpacks pode alterar a versão do runtime ou de bibliotecas do sistema sem qualquer mudança no repositório. Diferenças entre o ambiente de desenvolvimento e o de produção não são detectáveis antecipadamente. A migração para outra plataforma exigiria reconstruir todo o processo de build. O `requirements.txt` utiliza restrições de versão mínima (`>=`) sem fixação, permitindo que builds em datas diferentes instalem versões distintas das dependências.

**Recomendação**
Definir a imagem de contêiner explicitamente, fixando a versão do runtime. Adotar arquivo de dependências com versões travadas, mantendo o arquivo de restrições de alto nível separado. Isso garante builds determinísticos e viabiliza execução idêntica em qualquer ambiente.

---

### INFRA-07 — Ausência de gestão de segredos

**Severidade:** Média
**Categoria:** Infraestrutura / Segurança
**Prioridade:** Médio prazo

**Evidência**
Os segredos são fornecidos como variáveis de ambiente configuradas no painel da plataforma. Não há rotação, versionamento, auditoria de acesso ou integração com cofre de segredos.

**Impacto**
Rotacionar a `SECRET_KEY` invalida todas as sessões ativas simultaneamente e, conforme SEC-11, destrói a correlação histórica de IPs pseudonimizados. A rotação da `MASTER_ENCRYPTION_KEY` é ainda mais problemática: as chaves de arquivo individuais foram cifradas com ela, e não existe mecanismo de reencriptação — a rotação tornaria todos os PDFs armazenados permanentemente inacessíveis. Não há registro de quem acessou ou alterou os segredos.

**Recomendação**
Implementar suporte a múltiplas chaves ativas para permitir rotação gradual: aceitar tanto a chave anterior quanto a nova durante o período de transição. Para a chave mestra, projetar e testar um procedimento de reencriptação. Avaliar cofre de segredos gerenciado, que oferece auditoria e rotação nativa.

---

### INFRA-08 — Ausência de estratégia de implantação sem interrupção

**Severidade:** Média
**Categoria:** Infraestrutura / Disponibilidade
**Prioridade:** Médio prazo

**Evidência**
`railway.toml` configura apenas política de reinício em caso de falha. Não há definição de implantação progressiva, verificação de prontidão antes de direcionar tráfego, ou procedimento de reversão automática.

**Impacto**
Cada implantação implica indisponibilidade. As migrações executam durante a inicialização, então o novo processo pode demorar a ficar pronto enquanto o anterior já foi encerrado. Uma implantação com defeito requer intervenção manual para reverter — sem detecção automática, o defeito permanece ativo até alguém notar. Como as migrações não são versionadas nem reversíveis (DB-02), reverter o código não reverte o schema.

**Recomendação**
Adotar implantação com sobreposição, mantendo a versão anterior ativa até que a nova responda ao healthcheck. Separar a execução de migrações da inicialização da aplicação. Estabelecer critério automático de reversão baseado em taxa de erro após a implantação.

---

## 9. Achados — Performance e Escalabilidade

### PERF-01 — Ausência completa de camada de cache

**Severidade:** Alta
**Categoria:** Performance
**Prioridade:** Curto prazo

**Evidência**
Não há Redis, memcached ou cache em memória de aplicação. O único mecanismo de cache existente é o dicionário de contagem de comentários com escopo de requisição (`_COMMENT_COUNT_CACHE` em `app/routers/invoices_helpers.py`) e o cache de consultas de CNPJ persistido em tabela.

**Impacto**
Toda requisição de dashboard reexecuta o conjunto completo de consultas. Dados que praticamente não mudam — lista de diretores disponíveis, estrutura de setores, papel do usuário — são consultados a cada navegação. Com milhares de usuários ativos, o banco recebe carga proporcional ao número de páginas visitadas, quando a maior parte do conteúdo é idêntica entre requisições e entre usuários do mesmo perfil.

**Recomendação**
Introduzir cache distribuído para dados de baixa volatilidade: estrutura organizacional, listas de seleção, contadores agregados. Definir política de invalidação explícita para cada tipo. Priorizar os dados consultados em toda página, que oferecem o maior retorno.

---

### PERF-02 — Geração de comprovante síncrona no ciclo de requisição

**Severidade:** Alta
**Categoria:** Performance
**Prioridade:** Curto prazo

**Evidência**
`app/routers/print_routes.py`. Tanto `print_invoice` quanto `mark_paid` invocam `generate_print_pdf()` de forma síncrona. A função baixa cada anexo do armazenamento remoto, descriptografa, e concatena as páginas.

**Impacto**
Uma nota com cinco anexos exige cinco requisições de rede ao R2, cinco operações de descriptografia e a montagem de um documento potencialmente grande — tudo bloqueando o worker. Com dois workers, duas dessas operações simultâneas tornam a aplicação indisponível. O comprovante é regenerado integralmente a cada reimpressão, embora seu conteúdo seja idêntico após o lançamento da nota.

**Recomendação**
Gerar o comprovante uma única vez no momento do lançamento, armazená-lo, e servir o arquivo pronto nas reimpressões — o modelo já possui o campo `print_drive_file_id` reservado para isso, atualmente não utilizado. Para a geração inicial, considerar processamento assíncrono com notificação de conclusão.

---

### PERF-03 — Descriptografia repetida na visualização de anexos

**Severidade:** Alta
**Categoria:** Performance
**Prioridade:** Curto prazo

**Evidência**
`app/routers/invoices_attachments.py`, endpoint `get_attachment_merged`. Executado a cada abertura do visualizador de PDF na interface. Baixa todos os anexos do R2, descriptografa cada um e os concatena.

**Impacto**
Um aprovador que abra a mesma nota cinco vezes durante a análise dispara cinco ciclos completos de download, descriptografia e concatenação. O custo de banda com o provedor de armazenamento é proporcional. Como o visualizador é o fluxo principal de trabalho do aprovador, esta é uma das operações mais frequentes do sistema.

**Recomendação**
Aplicar cache do resultado concatenado, invalidado quando os anexos forem alterados. Alternativamente, servir os anexos individualmente com URLs assinadas de curta duração, transferindo o custo de entrega para o provedor de armazenamento.

---

### PERF-04 — Ausência de compressão configurada corretamente

**Severidade:** Média
**Categoria:** Performance
**Prioridade:** Médio prazo

**Evidência**
`app/main.py` configura compressão para respostas acima de 500 bytes. Os arquivos estáticos são servidos com cabeçalho de cache de 24 horas.

**Impacto**
A compressão está ativa, o que é positivo. O problema é a interação com o versionamento de assets (FE-03): 24 horas de cache com invalidação por parâmetro de consulta significa que uma correção urgente no JavaScript pode não alcançar usuários por um dia inteiro. Não há distinção entre assets imutáveis, que poderiam ter cache muito mais longo, e recursos que mudam.

**Recomendação**
Incorporar o hash de conteúdo ao nome dos arquivos e aplicar cache imutável de longa duração. Isso elimina simultaneamente o problema de invalidação lenta e reduz revalidações desnecessárias.

---

### PERF-05 — Contagem de comentários dependente de contexto implícito

**Severidade:** Média
**Categoria:** Performance
**Prioridade:** Médio prazo

**Evidência**
`app/routers/invoices_helpers.py`. A função `count_comments()` consulta uma variável de contexto preenchida por `prefetch_comment_counts()`. Quando a variável está vazia, executa consulta individual por nota.

**Impacto**
A otimização funciona apenas se o caminho de código lembrar de chamar o pré-carregamento antes de iterar. Qualquer novo endpoint que serialize múltiplas notas sem essa chamada retorna ao padrão de uma consulta por registro. A dependência é implícita e não verificável pelo sistema de tipos nem pelos testes atuais.

**Recomendação**
Tornar a dependência explícita: a função de serialização recebe as contagens como parâmetro, ou a consulta principal já as inclui via agregação. Isso elimina a possibilidade de esquecimento.

---

### PERF-06 — Ausência de paginação em endpoints de listagem secundários

**Severidade:** Média
**Categoria:** Performance
**Prioridade:** Curto prazo

**Evidência**
`GET /api/admin/users` retorna todos os usuários sem paginação. `GET /api/admin/departments` retorna todos os setores, cada um com a contagem de membros e a lista de diretores. `GET /api/invoices/directors` retorna todos os diretores com seus setores.

**Impacto**
Em organização com milhares de colaboradores, a listagem de usuários transfere o registro completo de cada um — incluindo dados pessoais — em uma única resposta. O carregamento das relações de setor por usuário multiplica as consultas. A interface administrativa filtra no cliente, o que exige receber tudo antes de exibir qualquer coisa.

**Recomendação**
Aplicar paginação com filtro no servidor a todas as listagens que crescem com o tamanho da organização. Ajustar a interface para consultar conforme a navegação do usuário.

---

### PERF-07 — Ausência de teste de carga

**Severidade:** Média
**Categoria:** Performance
**Prioridade:** Curto prazo

**Evidência**
Não há qualquer artefato de teste de carga ou desempenho no repositório. A suíte de 106 testes valida comportamento funcional exclusivamente.

**Impacto**
Os limites operacionais do sistema são desconhecidos. Não se sabe quantos usuários simultâneos são suportados, qual endpoint satura primeiro, ou como a latência evolui com o volume de dados. Os gargalos identificados nesta auditoria são deduzidos da leitura do código — sua magnitude real não foi medida. Planejar capacidade sem esses dados é adivinhação.

**Recomendação**
Estabelecer teste de carga cobrindo os fluxos principais, executado contra base de dados com volume representativo. Registrar as métricas obtidas como linha de base e incorporar a execução periódica ao processo de entrega.

---

## 10. Achados — Confiabilidade

### CONF-01 — Ponto único de falha na base de dados

**Severidade:** Alta
**Categoria:** Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
Instância única de PostgreSQL fornecida pela plataforma. Não há réplica de leitura, failover automático ou distribuição geográfica.

**Impacto**
Indisponibilidade do banco significa indisponibilidade total do sistema — não há degradação parcial. Toda a carga de leitura, incluindo as consultas pesadas de alertas e listagens, concorre com as escritas na mesma instância. Manutenção programada da plataforma implica interrupção do serviço.

**Recomendação**
Avaliar configuração com réplica, direcionando consultas de leitura intensiva para ela. Definir e testar o procedimento de failover. Estabelecer acordo de nível de serviço com a plataforma compatível com a criticidade do sistema.

---

### CONF-02 — Ausência de degradação graciosa em falha de armazenamento

**Severidade:** Alta
**Categoria:** Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
`app/services/drive_service.py`. Quando as credenciais do R2 estão configuradas, todas as operações dependem de sua disponibilidade. O fallback para armazenamento local existe apenas quando as credenciais estão ausentes — não como resposta a falha.

**Impacto**
Indisponibilidade do R2 impede completamente a criação de notas, já que o anexo é obrigatório. A visualização de documentos existentes também falha. O fluxo de aprovação inteiro é interrompido. Não há fila de reprocessamento nem armazenamento temporário que permitisse aceitar o upload e sincronizar posteriormente.

**Recomendação**
Implementar armazenamento temporário com sincronização assíncrona, permitindo que o upload seja aceito mesmo durante indisponibilidade do provedor. Sinalizar claramente ao usuário quando um documento ainda não foi persistido definitivamente.

---

### CONF-03 — Falha silenciosa no processamento da fila de e-mails

**Severidade:** Alta
**Categoria:** Confiabilidade
**Prioridade:** Curto prazo

**Evidência**
`app/services/email_queue_service.py`. O worker é iniciado condicionalmente e, conforme BE-04, pode não executar dependendo do contexto de loop de eventos. Não há verificação de que esteja ativo, nem métrica de profundidade da fila, nem alerta sobre mensagens envelhecidas.

**Impacto**
Se o worker não estiver funcionando, as mensagens acumulam-se indefinidamente sem qualquer sinal. Códigos de redefinição de senha nunca chegam — usuários ficam sem acesso e não sabem por quê. Notificações de aprovação pendente não são entregues — notas param na fila sem que o aprovador saiba. O sistema aparenta funcionar normalmente; a falha só se manifesta como reclamações difusas de usuários.

**Recomendação**
Expor a profundidade da fila e a idade da mensagem mais antiga como métricas monitoradas, com alerta ao ultrapassar limites. Adicionar verificação de vitalidade do worker ao healthcheck de prontidão. Considerar processo dedicado, cuja ausência seja detectável pela plataforma.

---

### CONF-04 — Ausência de plano de recuperação de desastre

**Severidade:** Alta
**Categoria:** Confiabilidade
**Prioridade:** Médio prazo

**Evidência**
Não há documentação de procedimento de recuperação, objetivos de ponto e tempo de recuperação, ou registro de exercício de restauração.

**Impacto**
Diante de perda de dados ou indisponibilidade prolongada da plataforma, a recuperação seria improvisada. Não se sabe quanto tempo levaria, nem se seria bem-sucedida. Para um sistema que armazena documentos fiscais com obrigação legal de retenção de cinco anos, a perda de dados tem consequências que vão além da operação.

**Recomendação**
Documentar o procedimento completo, incluindo a ordem de restauração de banco e armazenamento de objetos. Executar exercício de recuperação em ambiente isolado, medindo o tempo real. Revisar periodicamente.

---

### CONF-05 — Estado inconsistente entre banco e armazenamento de objetos

**Severidade:** Média
**Categoria:** Confiabilidade / Integridade
**Prioridade:** Médio prazo

**Evidência**
`app/services/invoice_service/attachments.py`, função `_add_attachments()`. O upload para o R2 ocorre antes do commit da transação. Em caso de falha subsequente, o arquivo permanece no armazenamento sem registro correspondente no banco. Inversamente, `fsm.py` na exclusão de notas registra falhas de remoção no R2 apenas como texto no log de auditoria.

**Impacto**
Divergência progressiva entre os dois repositórios. Arquivos órfãos acumulam custo e representam retenção de documentos que deveriam ter sido eliminados — relevante para conformidade com regras de privacidade. Não há processo de reconciliação que detecte ou corrija a divergência.

**Recomendação**
Implementar processo periódico de reconciliação que identifique objetos sem referência e referências sem objeto, reportando as discrepâncias. Adotar padrão de escrita em duas fases: registrar a intenção antes do upload e confirmar após, permitindo identificar operações incompletas.

---

## 11. Achados — Qualidade de Código

### QA-01 — Cobertura de testes com lacunas em áreas críticas

**Severidade:** Média
**Categoria:** Qualidade de Código
**Prioridade:** Curto prazo

**Evidência**
A suíte possui 106 testes cobrindo máquina de estados, matriz de permissões, isolamento entre setores, regressões de segurança, validação, comentários, administração e cadeia de auditoria. Não há cobertura para: upload e recuperação de anexos, geração de comprovante em PDF, fluxo completo de ações administrativas pendentes com manipulação de tempo, processamento da fila de e-mails sob falha, e comportamento do sistema sob concorrência.

**Impacto**
As áreas descobertas concentram vários dos achados desta auditoria. A duplicação de rota (BE-03) não é detectada. A condição de corrida em lançamento (DB-06) não é exercitada. A verificação de segurança de PDF (SEC-10) não tem teste que valide os caminhos de contorno. Refatorações nessas áreas não têm rede de proteção — exatamente as áreas mais delicadas.

**Recomendação**
Estender a cobertura priorizando: fluxo de anexos com simulação do armazenamento, geração de comprovante validando presença dos anexos no resultado, ações pendentes com controle de tempo, e cenários de concorrência nas transições de estado. Adicionar verificação que detecte rotas registradas em duplicidade.

---

### QA-02 — Documentação técnica divergente do código

**Severidade:** Baixa
**Categoria:** Qualidade de Código
**Prioridade:** Longo prazo

**Evidência**
Além do caso descrito em FE-04, o `README.md` documenta a credencial padrão de administrador, e comentários no código referenciam mecanismos já alterados. A documentação em `docs/` é extensa e majoritariamente atualizada, mas contém referências a decisões revertidas.

**Impacto**
Documentação incorreta é pior que ausência de documentação, pois induz confiança indevida. Um novo integrante da equipe seguindo o README criaria a instância com a credencial documentada, perpetuando o problema descrito em SEC-01.

**Recomendação**
Remover a credencial do README. Estabelecer revisão da documentação como parte do processo de alteração de código, especialmente para decisões de segurança.

---

## 11-B. Achados adicionais da evidência dinâmica (Manus)

O registro completo de evidências do Manus (executado com o app rodando em `127.0.0.1:7145`, cobertura via `coverage`, e inventário recursivo de `app.routes`) trouxe detalhes que a auditoria estática não vê. Os itens abaixo complementam os já catalogados.

### QA-03 — `pytest` não declarado em `requirements.txt` **[novo — Manus]**

**Severidade:** Média
**Categoria:** Qualidade / Onboarding
**Prioridade:** Curto prazo

**Evidência**
A tentativa de rodar `pytest -q` em ambiente limpo falha porque o executável não está instalado. `requirements.txt` só lista dependências de runtime. Não há `requirements-dev.txt`, `pyproject.toml` com extras de dev nem seção equivalente.

**Impacto**
A suíte de 106 testes — que é o principal ativo de qualidade do projeto — depende de o desenvolvedor conhecer o segredo de "instale pytest à parte". Um novo integrante seguindo `getting-started.md` provavelmente não roda os testes. Um pipeline de CI, quando implementado (INFRA-01), tem que redescobrir a dependência. Ferramentas de auditoria automatizada da cadeia de suprimento não veem a ferramenta que valida o próprio código.

**Recomendação**
Adicionar `requirements-dev.txt` (ou extras em `pyproject.toml`) declarando `pytest`, `pytest-asyncio` se aplicável, `httpx` na versão compatível com `TestClient`, e `coverage`. Referenciar em `getting-started.md` e no futuro workflow de CI.

---

### QA-04 — Cobertura de testes desigual em módulos críticos **[novo — Manus]**

**Severidade:** Média
**Categoria:** Qualidade
**Prioridade:** Curto prazo

**Evidência**
Medição do Manus com `coverage` sobre a suíte completa: 71% geral. Módulos abaixo desse patamar, com sua cobertura observada:

| Módulo | Cobertura | Comentário |
|---|---|---|
| `app/services/invoice_service/attachments.py` | 17% | Upload/download de anexos — caminho principal de negócio |
| `app/security/page_auth.py` | 28% | Guard das páginas HTML — onde SEC-20 vive |
| `app/routers/pending_actions.py` | 30% | Janela de 24h — controle anti-admin-malicioso |
| `app/routers/admin_users.py` | 31% | Criação/edição/desativação de usuários |
| `app/services/document_service.py` | 31% | Validação CPF/CNPJ + cache CNPJ |
| `app/services/drive_service.py` | 34% | R2 + criptografia por arquivo |
| `app/routers/pages.py` | 40% | Roteamento HTML |
| `app/services/invoice_service/queries.py` | 40% | Visibilidade + filtros — coração da autorização |

**Impacto**
As áreas menos testadas coincidem com as de maior risco: anexos (17%), page guard (28%), consultas com autorização (40%), ações administrativas de longa janela (30%). Justamente onde a auditoria dinâmica encontrou vulnerabilidades (SEC-20 mora em `page_auth.py`), a cobertura é a mais baixa. Não é coincidência estatística — é sinal de que os controles sem exercício automatizado tendem a divergir da promessa documentada.

**Recomendação**
Priorizar cobertura de `page_auth.py`, `attachments.py` e `queries.py` no próximo ciclo. Estabelecer meta mínima (60% por módulo, 80% no consolidado) e travar no CI. A meta agregada de 71% mascara a fragilidade das áreas críticas.

---

### DOC-01 — Divergências documentais extensivas **[novo — Manus, expande API-01]**

**Severidade:** Média
**Categoria:** Documentação / Contrato
**Prioridade:** Curto prazo

**Evidência**
Além das divergências de rotas já apontadas em API-01, o Manus catalogou outras discrepâncias entre documentação e código:

- **`docs/testing.md`, `docs/getting-started.md`, `docs/operations.md`, `docs/README.md` e `decisoes-2026-06-03.md`** afirmam "21 testes"; a suíte real tem 106.
- **`docs/api-reference.md`** documenta `/manager-review` — código expõe `/review`.
- **`docs/api-reference.md`** e **`docs/security.md`/`database.md`** referenciam `/veto` — código expõe `/cancel` e `/confirm`.
- **`docs/api-reference.md`** documenta PATCH para update administrativo — código usa PUT.
- **`docs/api-reference.md`** documenta `/close` e `/assign-director` — código usa `/anonymize` e `director_ids` no PUT do setor.
- **`docs/api-reference.md`** documenta `/api/invoices/{id}/attachment` como listagem e `/attachment/{attachment_id}` — código usa `/attachment` para PDF mesclado e `/attachments/{att_id}` para arquivo individual.
- **TTL do reset de senha** aparece em três valores diferentes: `docs/database.md` diz 5 minutos, FAQ diz 10 minutos, código usa 15 minutos.
- **`docs/operations.md`** referencia variável `TRUSTED_PROXIES` que **não existe no código**.
- **`docs/security.md`** descreve rate-limit por token JWT; o middleware efetivamente usa IP do socket ou primeiro elemento de `X-Forwarded-For`.
- **`docs/plan-refactor-master.md`** marca fases 1.1, 1.2, 2, 3.1, 3.2, 4 e 5 como pendentes, apesar de o repositório já conter os arquivos resultantes desses splits (auth_session/password, health/static_views, pacote invoice_service, módulos JS refatorados).
- **`docs/frontend.md`** descreve 19/21 módulos JavaScript; a implementação tem 30 arquivos.

**Impacto**
Um cliente de API seguindo `api-reference.md` recebe 404 ou 405 em cinco padrões distintos. Um operador seguindo `operations.md` configura `TRUSTED_PROXIES` no ambiente e não obtém efeito algum — a interpretação de `X-Forwarded-For` fica silenciosamente sem hardening (o que reforça SEC-06). Um usuário sob suporte é informado que o código expira em 10 minutos e vê expiração em 15. Um novo desenvolvedor lendo o plano de refatoração conclui que o trabalho ainda está por fazer.

**Recomendação**
Adotar a implementação como fonte canônica. Duas linhas de defesa: gerar a referência de API a partir do `/openapi.json` real (elimina divergências de rota), e adicionar teste de contrato no CI comparando as rotas documentadas com `app.routes`. Escolher um único TTL para reset de senha e propagar por doc + FAQ + código. Remover ou implementar `TRUSTED_PROXIES`. Marcar `plan-refactor-master.md` como concluído nas fases já entregues, ou arquivar o documento e substituir por um retrospectivo.

---

### INFRA-09 — Migrações incompatíveis com SQLite tratadas como warnings **[expandido — Manus]**

**Severidade:** Média
**Categoria:** Banco de Dados / Infraestrutura
**Prioridade:** Curto prazo

**Evidência**
A auditoria dinâmica capturou as quatro migrações que falham em SQLite e são apenas registradas como warning por `run_schema_migrations()`:

1. `ALTER TABLE users DROP COLUMN IF EXISTS department` — sintaxe não suportada em SQLite (só permite `DROP COLUMN` a partir de 3.35 sem `IF EXISTS`).
2. `ALTER TYPE approvalaction ADD VALUE 'TRANSFERRED_DIRECTOR'` — SQLite não tem `ALTER TYPE`.
3. `CREATE EXTENSION unaccent` — SQLite não tem sistema de extensões PostgreSQL.
4. `ALTER TYPE userrole ADD VALUE 'CONTAS_A_PAGAR'` — mesma limitação de (2).

**Impacto**
DEV em SQLite roda sobre um schema levemente diferente de PROD. Notas com status `TRANSFERRED_DIRECTOR` ou usuários com role `CONTAS_A_PAGAR` funcionam porque os enums do SQLAlchemy são traduzidos para VARCHAR em SQLite (aceita qualquer valor), mas testes que dependem de restrição de coluna, extensão `unaccent` (busca acento-insensível), ou coluna já removida podem passar em SQLite e falhar em PostgreSQL — ou vice-versa. Isso mina a promessa de que a suíte local reflete o comportamento de produção.

**Recomendação**
Separar migrações por dialeto — o próprio `engine.dialect.name` está disponível. Idempotência real por banco: para SQLite, ou pular o comando com log explícito, ou reescrever equivalente (recriação de tabela via `CREATE TABLE AS SELECT` no caso de DROP COLUMN). A migração para Alembic (DB-02) resolve isso estruturalmente: cada revisão declara qual dialeto suporta.

---

### INFRA-10 — `bcrypt.__about__.__version__` acionando warning trapped **[novo — Manus]**

**Severidade:** Baixa
**Categoria:** Dependências
**Prioridade:** Longo prazo

**Evidência**
Ao subir a aplicação, passlib emite `(trapped) error reading bcrypt version` porque a versão instalada de `bcrypt` (>=4.1) removeu o módulo `__about__`. O `requirements.txt` já pina `bcrypt>=4.0.1,<5`, mas o intervalo alcança versões incompatíveis com a introspecção de passlib.

**Impacto**
O sistema de hashing continua funcionando — o trapped error é diagnóstico, não bloqueio. Mas o warning aparece em toda inicialização e polui a análise de logs, dificultando triagem quando algo real falhar. Também sinaliza que passlib está em manutenção mínima; para a evolução do algoritmo de hash, alternativas modernas (argon2 via `argon2-cffi`, ou bcrypt direto sem passlib) merecem consideração.

**Recomendação**
Fixar `bcrypt` em versão compatível com a passlib instalada, ou migrar para `argon2-cffi` como algoritmo primário mantendo bcrypt como fallback para hashes legados. Documentar o warning como conhecido enquanto persistir.

---

### UX-02 — Link "Reativar" na tela de indisponibilidade não responde ao clique **[novo — Manus]**

**Severidade:** Baixa
**Categoria:** Frontend / UX
**Prioridade:** Longo prazo

**Evidência**
Na tela de configurações do gestor/diretor, o link textual "Reativar" no banner de indisponibilidade não altera a tela ao clique direto. A alternância só funciona pelo checkbox principal, que exibe corretamente o banner verde de disponibilidade.

**Impacto**
Baixo — o caminho principal (checkbox) funciona. Mas o link duplicado sinaliza afordância enganosa: o usuário clica em "Reativar" esperando ação e não obtém feedback.

**Recomendação**
Ou fazer o link "Reativar" acionar o mesmo handler do checkbox, ou removê-lo se for redundante.

---

### UX-03 — `/offline.html` "Tentar de novo" não retorna à aplicação **[novo — Manus, verificar]**

**Severidade:** Baixa
**Categoria:** Frontend / PWA
**Prioridade:** Médio prazo

**Evidência**
Acessando `/offline.html` diretamente com conexão disponível, o botão "Tentar de novo" não navegou para a aplicação. Como a página foi aberta fora do fluxo natural (SW não a serviu por falta de conexão), o comportamento pode ser artefato do modo de teste — mas o próprio Manus registra que precisa ser validado com Service Worker real.

**Impacto**
Baixo em uso normal, porque a página só aparece quando o SW detecta ausência de rede. Mas se o botão de fato não navega mesmo quando a conexão volta, o usuário precisa recarregar manualmente — degrada a promessa de PWA suave.

**Recomendação**
Reproduzir em cenário controlado (DevTools "offline" → "online") e ajustar o handler do botão para forçar `location.reload()` ou navegação para `/`.

---

### UX-04 — Botão "Verificar cadeia de auditoria" não visível na UI **[novo — Manus]**

**Severidade:** Média
**Categoria:** Frontend / Segurança operacional
**Prioridade:** Curto prazo

**Evidência**
O Manus abriu `/admin/audit-logs` e não localizou controle textual para invocar `/api/admin/audit-logs/verify-chain` no viewport inicial. O endpoint existe e tem cobertura de teste — mas se o operador (admin) não tem como acionar pela interface, ele nunca vai correr essa verificação.

**Impacto**
Para um controle que existe justamente para detectar adulteração de audit logs, ser inacessível pela UI é falha operacional. Combinado com DB-01 (bifurcação da cadeia), o admin não descobre a violação nem verificando ativamente — e não verifica ativamente porque não há botão.

**Recomendação**
Adicionar botão explícito "Verificar integridade da cadeia" na página de audit logs, com resultado visual claro (verde = íntegra, vermelho = violação detectada em linha X). Considerar execução automática periódica com alerta para admin.

---

### UX-05 — Redirecionamento após `/forgot-password` não observado **[novo — Manus, verificar]**

**Severidade:** Baixa
**Categoria:** Frontend / UX
**Prioridade:** Longo prazo

**Evidência**
Após envio do email em `/forgot-password`, o Manus observou a mensagem genérica correta ("Se este email estiver cadastrado, você receberá um código..."), mas o redirecionamento para `/reset-password` prometido em 2,5s pela documentação não ocorreu no intervalo observado.

**Impacto**
Baixo — o usuário pode navegar manualmente. Mas se o timer quebrou, é regressão silenciosa.

**Recomendação**
Reproduzir com espera maior e inspecionar o `setTimeout` do template. Ajustar teste automatizado se possível.

---

## 12. Priorização consolidada

### Prioridade imediata — antes de qualquer uso em produção

| ID | Título | Severidade | Origem |
|---|---|---|---|
| SEC-20 | Logout não invalida refresh cookie nem page guard | Crítica | Manus |
| SEC-01 | Credenciais de administrador padrão hardcoded | Crítica | A |
| SEC-02 | "Assinatura digital" sem segredo criptográfico | Crítica | A |
| SEC-03 | Endpoint público `/verify` sem rate limit | Crítica | A |
| DB-01 | Bifurcação da hash chain sob concorrência | Crítica | A |
| INFRA-01 | Ausência de pipeline de integração contínua | Crítica | convergente |
| SEC-04 | Rate limit em memória por processo | Alta | A |
| INFRA-02 | Healthcheck não verifica dependências | Alta | A |
| DB-03 | Carregamento eager na listagem principal | Alta | A |
| DB-05 | Endpoint de alertas sem paginação | Alta | A |
| BE-03 | Endpoint `mark-paid` duplicado | Alta | convergente |
| SEC-10 | Fail-open na validação de PDF | Alta | convergente |
| APP-01 | Criação em DEV sem chave termina em 500 | Alta | Manus |
| FE-05 | Verify autenticado quebrado (sem `window.Auth`) | Alta | Manus |
| API-01 | Documentação da API divergente do código | Média | Manus |

### Prioridade curto prazo — próximas 4 a 6 semanas

| ID | Título | Severidade |
|---|---|---|
| SEC-05 | Cobertura de rate limit insuficiente | Alta |
| SEC-06 | `X-Forwarded-For` confiado sem validação | Alta |
| SEC-07 | Falha aberta quando `ENVIRONMENT` ausente | Alta |
| SEC-08 | `run-due` acessível a qualquer autenticado | Alta |
| SEC-09 | Injeção de HTML em e-mails | Alta |
| SEC-10 | Detecção de PDF malicioso contornável | Alta |
| SEC-12 | `verify-full` expõe e-mails sem máscara | Média |
| SEC-18 | Divergência de limites de valor | Baixa |
| SEC-19 | Bases de dados no diretório de trabalho | Informativa |
| DB-02 | Migrações sem versionamento | Alta |
| DB-04 | Total via subconsulta sobre query completa | Alta |
| DB-06 | Condição de corrida em lançamento | Média |
| DB-07 | Purga concorrente entre workers | Média |
| DB-08 | Índices ausentes para consultas reais | Média |
| BE-01 | Supressão silenciosa de exceções | Alta |
| BE-02 | Ausência de timeout de requisição | Alta |
| BE-03 | Endpoint duplicado | Alta |
| BE-08 | Concatenação de PDF sem limite | Média |
| FE-01 | Dezenove scripts em todas as páginas | Alta |
| INFRA-03 | Observabilidade limitada | Alta |
| INFRA-04 | Backup não verificado | Alta |
| INFRA-05 | Workers fixos e insuficientes | Alta |
| PERF-01 | Ausência de cache | Alta |
| PERF-02 | PDF gerado sincronamente | Alta |
| PERF-03 | Descriptografia repetida | Alta |
| PERF-06 | Listagens sem paginação | Média |
| PERF-07 | Ausência de teste de carga | Média |
| CONF-03 | Falha silenciosa na fila de e-mails | Alta |
| QA-01 | Lacunas na cobertura de testes | Média |

### Prioridade médio prazo — próximo trimestre

SEC-11, SEC-13, SEC-14, SEC-15, SEC-16, DB-09, BE-04, BE-05, BE-06, ARQ-01, ARQ-02, ARQ-04, FE-02, FE-03, INFRA-06, INFRA-07, INFRA-08, PERF-04, PERF-05, CONF-01, CONF-02, CONF-04, CONF-05

### Prioridade longo prazo

SEC-17, DB-10, BE-07, ARQ-03, ARQ-05, FE-04, QA-02

---

## 13. Riscos para produção

### O que quebra primeiro sob carga

Com base na análise, a ordem provável de falha conforme o tráfego cresce:

**Entre 50 e 100 usuários simultâneos.** O endpoint de alertas (DB-05) torna-se o gargalo dominante. Cada navegação dispara cinco consultas sem limite com carregamento eager completo. A latência do dashboard cresce visivelmente. Os dois workers passam a ficar ocupados com frequência, e requisições começam a enfileirar.

**Entre 100 e 300 usuários simultâneos.** A listagem principal (DB-03, DB-04) satura o banco. As três varreduras por requisição — contagem, soma e paginação — sobre conjuntos com carregamento eager tornam o tempo de resposta inaceitável. A geração de comprovantes (PERF-02) começa a bloquear workers por períodos que afetam todas as demais requisições.

**Acima de 300 usuários simultâneos.** Esgotamento de workers. Sem timeout configurado (BE-02), requisições lentas acumulam-se indefinidamente. O healthcheck, que não verifica nada (INFRA-02), continua reportando saúde enquanto o sistema não atende ninguém. Não há alerta configurado (INFRA-03), então a equipe descobre pelo canal de suporte.

### O que falha independentemente de carga

**A cadeia de auditoria já pode estar comprometida.** Com dois workers em operação, a bifurcação descrita em DB-01 é questão de probabilidade, não de possibilidade. Recomenda-se verificar imediatamente o resultado do endpoint de verificação — se já reporta violação, o mecanismo está inoperante desde algum ponto do passado, e a decisão sobre como proceder precisa ser tomada com registro formal.

**A fila de e-mails pode não estar processando.** Conforme BE-04 e CONF-03, o worker pode não ter sido iniciado corretamente, sem qualquer sinalização. Verificar se há mensagens antigas em estado pendente na tabela é diagnóstico direto.

**Comprovantes podem estar incompletos.** A supressão silenciosa na concatenação de anexos (BE-01) significa que um comprovante pode ter sido gerado sem os documentos que deveria conter, e ninguém saberia.

### Riscos de segurança com exploração viável

O comprometimento mais direto é a credencial padrão (SEC-01) em qualquer ambiente ainda não personalizado. A forja de comprovantes (SEC-02) exige conhecimento do formato mas não de segredo algum — é viável para qualquer pessoa com acesso a um comprovante legítimo e capacidade de editar PDF. A injeção de HTML em e-mails (SEC-09) é explorável por qualquer gestor do sistema, com resultado convincente para phishing interno.

---

## 14. Análise de escalabilidade (10x / 100x)

### Cenário atual estimado

Dado o dimensionamento (dois workers, instância única de banco, sem cache), a estimativa é de suporte confortável a algumas dezenas de usuários simultâneos, com degradação perceptível a partir de aproximadamente cinquenta.

### O sistema suportaria 10x mais usuários?

**Não sem alterações.** Os obstáculos, em ordem de impacto:

O endpoint de alertas precisaria ser reformulado — atualmente transfere volume proporcional ao total de notas do usuário, a cada navegação. Sem paginação e separação entre contagem e listagem, nenhum aumento de infraestrutura resolve.

O rate limiting precisaria migrar para armazenamento compartilhado, caso contrário o aumento de instâncias multiplica proporcionalmente a capacidade de abuso.

A cadeia de auditoria precisaria de serialização adequada, pois mais workers significam mais bifurcações.

O número de workers precisaria crescer, com o pool de conexões dimensionado adequadamente, o que provavelmente exigiria um pooler de conexões entre a aplicação e o banco.

Estimativa de esforço: quatro a seis semanas concentradas nos itens de prioridade imediata e curto prazo.

### O sistema suportaria 100x mais usuários?

**Não com a arquitetura atual.** Além de tudo acima, seriam necessárias mudanças estruturais:

Separação de leitura e escrita, com réplicas dedicadas às consultas de listagem e alertas, que dominam o volume.

Camada de cache distribuído para dados de baixa volatilidade — estrutura organizacional, listas de seleção, agregações.

Processamento assíncrono para todas as operações custosas: geração de comprovantes, montagem de anexos, envio de notificações. O modelo atual de executar tudo no ciclo de requisição não sustenta esse volume.

Reformulação do modelo de consultas, substituindo a materialização de entidades completas por projeções específicas para cada caso de uso.

Particionamento da tabela de auditoria por período, dado que ela cresce monotonicamente e é consultada a cada inserção.

Entrega de documentos via URLs assinadas diretamente do provedor de armazenamento, retirando a aplicação do caminho de transferência de arquivos.

Estimativa de esforço: três a seis meses, com revisão arquitetural conduzida por quem conheça o domínio.

### Módulos que limitam o crescimento

Em ordem de restrição: o serviço de alertas, as consultas de listagem de notas, a geração de PDF, o mecanismo de rate limiting, a cadeia de auditoria, e o sistema de migrações.

---

## 15. Recomendações estratégicas

**Estabelecer a rede de proteção antes de continuar evoluindo funcionalidades.** O sistema possui 106 testes que ninguém é obrigado a executar. Um pipeline de integração contínua é o investimento de maior retorno imediato: transforma trabalho já realizado em garantia efetiva. Sem isso, cada refatoração futura carrega o mesmo risco que as recentes carregaram.

**Tratar observabilidade como requisito, não como melhoria.** A ausência de alertas significa que qualquer incidente tem duração determinada pelo tempo que um usuário leva para reclamar. Para um sistema que controla aprovação de pagamentos, isso é inaceitável em ambiente corporativo. Captura de exceções e alerta sobre indicadores fundamentais devem preceder qualquer nova funcionalidade.

**Resolver os gargalos de consulta antes de escalar infraestrutura.** Os problemas de alertas e listagem não são resolvíveis com mais servidores — o volume transferido é proporcional aos dados, não à capacidade. Corrigi-los provavelmente entrega ganho maior que qualquer aumento de recursos, e a preço muito menor.

**Reavaliar a promessa de autenticidade dos comprovantes.** O sistema imprime "Assinatura Digital" em documentos que autorizam pagamento, sem que exista assinatura no sentido criptográfico. Além da correção técnica, convém verificar se algum processo interno ou externo depende dessa garantia, pois pode haver exposição já materializada.

**Adotar migrações versionadas antes que o schema divirja entre ambientes.** O modelo atual funciona enquanto há um ambiente e um operador. Com múltiplos ambientes ou equipe maior, a ausência de controle de versão produz divergências difíceis de diagnosticar e impossíveis de reverter.

**Reconsiderar a restrição de "sem etapa de build" no frontend.** A decisão é defensável e reduziu complexidade operacional. Contudo, dezenove scripts carregados incondicionalmente em toda página é custo real para o usuário. Carregamento condicional por página resolve boa parte do problema sem introduzir ferramental de build.

---

## 16. Roadmap sugerido

### Fase 1 — Estabilização (semanas 1 e 2)

Foco em eliminar riscos que já existem hoje.

Remover a credencial padrão do código e do README; rotacionar em ambientes existentes. Substituir a assinatura de comprovantes por construção com segredo. Adicionar rate limit ao endpoint público de verificação. Verificar e corrigir o estado da cadeia de auditoria, implementando serialização. Estabelecer pipeline de integração contínua executando a suíte existente. Corrigir o healthcheck para verificar dependências. Restringir o endpoint de execução de ações pendentes.

Resultado esperado: eliminação dos cinco achados críticos e de três achados altos de segurança.

### Fase 2 — Performance e observabilidade (semanas 3 a 6)

Foco em tornar o sistema capaz de sustentar carga real e detectável quando falhar.

Reformular o endpoint de alertas separando contagem de listagem. Ativar o modo de carregamento leve na listagem principal. Otimizar o cálculo de totais. Criar os índices compostos correspondentes aos padrões de consulta reais. Integrar captura de exceções com alerta. Expor métricas fundamentais, incluindo profundidade da fila de e-mails. Configurar timeout de requisição. Migrar o rate limiting para armazenamento compartilhado. Corrigir a supressão silenciosa nos pontos que mascaram falhas relevantes. Estabelecer teste de carga e registrar linha de base.

Resultado esperado: capacidade para uma ordem de magnitude a mais de usuários, com visibilidade operacional.

### Fase 3 — Robustez (semanas 7 a 12)

Foco em resiliência e conformidade.

Migrar para migrações versionadas. Documentar e exercitar o procedimento de recuperação. Habilitar versionamento no armazenamento de objetos e estabelecer cópia independente. Implementar cache distribuído para dados de baixa volatilidade. Mover a geração de comprovantes para processamento assíncrono com armazenamento do resultado. Corrigir a injeção de HTML em e-mails. Fortalecer a validação de PDF. Estender a cobertura de testes para as áreas descobertas. Containerizar com dependências fixadas.

Resultado esperado: sistema com recuperação testada e degradação controlada.

### Fase 4 — Evolução arquitetural (trimestre seguinte)

Foco em preparar para crescimento sustentado.

Eliminar as dependências circulares. Introduzir camada de transferência de dados para os casos de uso de maior volume. Desacoplar a camada de domínio do framework web. Consolidar as regras de autorização duplicadas. Avaliar réplica de leitura. Implementar circuit breakers. Estabelecer suporte a rotação de chaves.

---

## 17. Conclusão — maturidade técnica

### Avaliação por dimensão

| Dimensão | Nota | Comentário |
|---|---|---|
| Segurança de aplicação | 7,0 | Fundamentos sólidos e conscientes; falhas concentradas em pontos específicos |
| Arquitetura de código | 7,0 | Boa modularização recente; acoplamentos pontuais e camadas pouco definidas |
| Banco de dados | 5,0 | Modelagem adequada; consultas e migrações são o ponto fraco |
| Backend | 6,5 | Lógica correta; tratamento de falhas e controle de recursos deficientes |
| Frontend | 6,0 | Funcional e acessível; carregamento e segurança dependem de disciplina |
| Infraestrutura | 3,5 | Lacuna mais significativa: sem CI, sem observabilidade, sem backup testado |
| Performance | 4,5 | Gargalos identificados e não medidos; sem cache |
| Confiabilidade | 4,0 | Pontos únicos de falha; falhas silenciosas; sem plano de recuperação |
| Escalabilidade | 4,0 | Obstáculos estruturais para crescimento horizontal |
| Qualidade de código | 7,5 | Legível, bem comentado, com testes; lacunas em áreas críticas |
| **Média ponderada** | **6,0** | |

### Considerações finais

Este é um sistema construído com cuidado acima do que se observa tipicamente em projetos deste porte. A preocupação com segurança é genuína e visível: token de acesso mantido em memória em vez de armazenamento persistente do navegador, cadeia de hashes para detecção de adulteração em auditoria, pseudonimização de endereços para conformidade com privacidade, criptografia de documentos antes do envio ao armazenamento, política de conteúdo restritiva, e defesas explicitamente desenhadas contra o cenário de administrador malicioso. Três rodadas documentadas de teste de invasão com nove correções aplicadas demonstram um processo de melhoria contínua incomum.

O código é legível. Os comentários explicam decisões, não apenas descrevem o que a linha faz — há registro de por que uma abordagem foi escolhida e qual alternativa foi descartada. A refatoração recente, que dividiu seis arquivos de grande porte em módulos coesos, foi executada com disciplina: testes verdes antes e depois, verificação em ambiente real, e commits granulares que permitem reversão.

A distância entre o estado atual e um sistema pronto para ambiente corporativo não está no código de aplicação. Está no entorno operacional. Um sistema que processa aprovações financeiras precisa de portão de qualidade automatizado, precisa avisar quando falha, precisa ter backup que alguém já restaurou pelo menos uma vez, e precisa suportar a carga esperada com margem. Nenhuma dessas quatro condições está satisfeita hoje.

Os gargalos de performance identificados — particularmente o endpoint de alertas e a listagem principal — são consequência natural de decisões razoáveis tomadas quando o volume de dados era pequeno. Carregar o grafo completo de uma entidade é conveniente e correto para dezenas de registros. Torna-se inviável para dezenas de milhares. A correção é conhecida e o esforço é moderado.

Recomenda-se, em ordem: executar a Fase 1 do roadmap antes de qualquer uso em ambiente corporativo; verificar imediatamente se a cadeia de auditoria já bifurcou e se a fila de e-mails está processando, pois ambas as falhas são silenciosas e podem já estar ativas; e priorizar a Fase 2 antes de aumentar a base de usuários. Com quatro a seis semanas de trabalho focado, o sistema alcança confortavelmente a faixa de 8,0 e torna-se adequado ao cenário descrito.

---

*Documento gerado por auditoria estática do código-fonte. Nenhuma alteração foi realizada no sistema. Recomenda-se validação dos achados de performance através de teste de carga em ambiente com volume representativo, e dos achados de segurança através de teste de invasão em ambiente controlado.*
