# Documentação Economart

Documentação técnica do sistema de aprovação de notas fiscais.
Organizada para que qualquer dev — independente do nível — consiga
entender, contribuir e operar o sistema.

## Para começar

**Nunca rodou o sistema antes?** → [getting-started.md](getting-started.md)

Setup local em 6 passos, primeiro login, erros comuns na instalação.

## Como o sistema funciona

| Documento | O que cobre |
|---|---|
| [architecture.md](architecture.md) | Visão geral. Camadas, fluxos principais, diagramas. Começa aqui se você quer entender o sistema rapidamente |
| [domain-model.md](domain-model.md) | Modelo de domínio. Quem são os 6 papéis de usuário, máquina de estados da nota, regras de aprovação, indisponibilidade e substituto, comentários, auditoria, verify público. Documento que explica **o quê** o sistema faz |
| [security.md](security.md) | Mecanismos de segurança. Autenticação JWT + refresh, invalidação de sessão, hash de senhas, criptografia de PDFs, rate-limit, CSP, defesa contra admin malicioso, LGPD |
| [database.md](database.md) | Schema do banco. Tabelas, relações, índices, migrações, padrões de query, estratégia de backup |
| [api-reference.md](api-reference.md) | Referência dos endpoints HTTP. Auth, notas, comentários, admin, health checks. Códigos HTTP usados |
| [frontend.md](frontend.md) | Estrutura do frontend. Templates Jinja2, CSS organizado em partials, JavaScript vanilla, padrões de UI, acessibilidade |

## Operação e manutenção

| Documento | O que cobre |
|---|---|
| [operations.md](operations.md) | Deploy no Railway, variáveis de ambiente, provedores de email, troubleshooting comum, procedimentos manuais (trocar SECRET_KEY, backup, reset de senha do admin) |
| [testing.md](testing.md) | Suite pytest, como rodar, como adicionar testes novos. Cobertura atual: 21 testes verdes em ~12s |
| [faq.md](faq.md) | Perguntas técnicas frequentes com respostas curtas. Vai aqui se você tem um problema específico |

## Registro de decisões

| Documento | O que cobre |
|---|---|
| [decisoes-2026-06-03.md](decisoes-2026-06-03.md) | Decisões tomadas durante a auditoria de segurança. Cobre contexto, mudanças implementadas, bugs encontrados na execução, roadmap |

---

## Ordem recomendada de leitura

**Dev novo no projeto** (do zero ao produtivo em ~2h):

1. [getting-started.md](getting-started.md) — instalar e rodar
2. [architecture.md](architecture.md) — entender o sistema
3. [domain-model.md](domain-model.md) — entender o negócio
4. Pular para o documento da área que vai mexer

**Dev focado em backend**:
- [database.md](database.md) → [api-reference.md](api-reference.md)
  → [security.md](security.md)

**Dev focado em frontend**:
- [frontend.md](frontend.md) → [api-reference.md](api-reference.md)

**Dev focado em DevOps**:
- [operations.md](operations.md) → [security.md](security.md)
  → [testing.md](testing.md)

**QA / suporte**:
- [domain-model.md](domain-model.md) → [faq.md](faq.md)
  → [api-reference.md](api-reference.md)

---

## Princípios de documentação

Todos os documentos seguem três regras:

1. **Linguagem dupla**: visão geral acessível + detalhes técnicos.
   Qualquer pessoa entende o "o quê", devs entendem o "como"
2. **Explicar o porquê**: decisões de design e trade-offs ficam
   documentados. Não é só "o que fazer" — é "por que escolhemos
   assim"
3. **Onde isso vive no código**: cada documento conclui com
   tabela apontando os arquivos relevantes. Quem quer ir fundo
   sabe onde olhar

Para contribuir com a documentação, mantenha esses três princípios.
