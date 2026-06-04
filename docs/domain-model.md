# Modelo de domínio — papéis, fluxo e regras

Este documento explica **o que** o sistema faz: quem são os atores,
qual o caminho que uma nota fiscal percorre, e quais são as regras
de negócio importantes. Não fala de código — fala do processo.

## Glossário rápido

| Termo | Significado |
|---|---|
| **Nota fiscal** | Documento emitido por um fornecedor que precisa ser pago/lançado pela empresa |
| **Aprovação** | Ato de um superior validar que aquela despesa é legítima |
| **FSM** | Finite State Machine — máquina de estados. Cada nota só pode estar em um estado por vez |
| **Anexo** | PDF da nota original, comprovante de boleto, etc. |
| **Comprovante** | PDF que o sistema gera no fim do fluxo, com QR Code de verificação |
| **R2** | Cloudflare R2 — armazenamento de arquivos (equivalente ao S3 da Amazon) |

## Os papéis (roles)

O sistema tem 6 perfis de usuário, com permissões diferentes:

### 👤 EMPLOYEE (Funcionário)

- Cria notas fiscais
- Acompanha o status das suas notas
- Pode cancelar a própria nota antes do envio
- Reedita e reenvia notas reprovadas

**O que não pode**: ver notas de outros funcionários, aprovar nada,
gerar comprovante.

### 👔 MANAGER (Gestor)

- Aprova ou reprova notas da sua equipe
- Recebe email a cada nota nova na fila dele
- Pode marcar a si próprio como indisponível (modo férias)
- Pode designar outro gestor como substituto durante a ausência
- Também pode criar notas próprias (que entram no fluxo normal)

**O que não pode**: aprovar pelo diretor, lançar nota como paga,
ver notas de outros setores.

### 🎩 DIRECTOR (Diretor)

- Aprova ou reprova notas que já passaram pelo gestor
- Pode receber notas diretamente, pulando o gestor (quando o
  funcionário tem flag `submit_directly_to_director`)
- Tem mesma flag de indisponibilidade e substituto que o gestor
- Pode repassar uma nota para outro diretor durante a aprovação

**O que não pode**: lançar nota como paga (esse é o financeiro).

### 💰 FINANCE (Financeiro)

- Lança notas já aprovadas (transição APROVADO → PAGO)
- Gera o comprovante de recebimento em PDF
- Vê todas as notas APROVADAS e PAGAS, de qualquer setor
- Pode reimprimir comprovantes a qualquer momento

**O que não pode**: aprovar/reprovar notas, alterar dados da nota.

### 🔍 CONTAS_A_PAGAR (Conferência)

- Acesso somente leitura a todas as notas
- Reimprime comprovantes de notas já lançadas
- Tem **scanner QR Code** integrado para conferência rápida
  via /contas-a-pagar/scanner

**O que não pode**: criar, editar, aprovar, reprovar, ou lançar
qualquer coisa. É um perfil de auditoria operacional.

### 🛠 ADMIN

- Cria/edita/encerra usuários
- Cria/edita setores (departments)
- Vê log de auditoria
- Configura email do sistema
- **Não aprova notas** nem entra no fluxo financeiro

Decisão deliberada: o admin gerencia o sistema, mas não opera o fluxo
de negócio. Isso reduz o risco de um admin malicioso conseguir mover
notas indevidamente.

---

## Fluxo de aprovação (FSM)

Cada nota passa por estes estados, na ordem:

```
┌─────────────┐
│  RASCUNHO   │  funcionário criou, ainda não enviou
└──────┬──────┘
       │ (envia)
       │
┌──────▼────────────────┐
│  AGUARDANDO_GESTOR    │  na fila do gestor responsável
└──────┬─────────────┬──┘
       │             │
   (aprova)      (reprova)
       │             │
       ▼             ▼
┌──────────────┐  ┌──────────────────────┐
│ AGUARDANDO_  │  │  REPROVADO_GESTOR    │
│   DIRETOR    │  │  (volta editável)    │
└──────┬───────┘  └──────────────────────┘
       │
   (aprova ou reprova)
       │
   ┌───┴────┐
   ▼        ▼
┌──────────┐ ┌──────────────────────┐
│ APROVADO │ │  REPROVADO_DIRETOR   │
└────┬─────┘ └──────────────────────┘
     │
 (financeiro lança / imprime)
     │
     ▼
┌──────────┐
│   PAGO   │  fim do fluxo
└──────────┘
```

### Estados em detalhe

- **RASCUNHO**: criada mas não enviada. Editável e deletável pelo
  criador. Não aparece pra mais ninguém.

- **AGUARDANDO_GESTOR**: na fila do gestor do criador. O gestor pode
  aprovar (vai pro diretor) ou reprovar (com motivo obrigatório).

- **AGUARDANDO_DIRETOR**: na fila do diretor. Pode também ser para
  qualquer diretor, se o criador tem `submit_directly_to_director=True`
  (atalho que pula o gestor). Diretor pode aprovar, reprovar, ou
  **repassar** a nota para outro diretor.

- **APROVADO**: passou por gestor e diretor. Aparece na fila do
  financeiro pra lançamento.

- **PAGO**: o financeiro lançou. Internamente o sistema chama
  esse estado de "PAGO" mas a UI mostra como "Lançado" — o sistema
  não executa pagamento real, apenas registra que o financeiro
  formalizou.

- **REPROVADO_GESTOR / REPROVADO_DIRETOR**: nota volta editável para
  o criador. Ele edita e reenvia. **Regra anti-reenvio vazio**: se
  a descrição da nota não mudou em relação ao snapshot do momento
  da reprovação, o reenvio é bloqueado. Evita "reenviar igual" no
  reflexo.

### Transições especiais

- **Envio direto pro diretor**: funcionários com flag
  `submit_directly_to_director=True` pulam o gestor e escolhem
  diretamente um diretor disponível. Usado para níveis hierárquicos
  altos onde o gestor é o próprio criador.

- **Repasse entre diretores**: o diretor responsável atual pode
  transferir a nota para outro diretor com comentário obrigatório
  de pelo menos 10 caracteres. Fica registrado no histórico como
  `TRANSFERRED_DIRECTOR`.

- **Cancelamento**: criador pode cancelar a própria nota enquanto
  ela ainda está RASCUNHO ou nos estados de aguardar aprovação.
  Cancelamento volta a nota para RASCUNHO.

- **Auto-purge de reprovadas**: notas REPROVADO_GESTOR e
  REPROVADO_DIRETOR são automaticamente apagadas após 90 dias,
  junto com seus anexos. Liberação automática de espaço.

---

## Indisponibilidade e substituto (modo férias)

Tanto Gestores quanto Diretores podem se marcar como
**indisponíveis** (em Configurações → Indisponibilidade). Quando
indisponíveis:

- Não recebem notas novas
- Notas já na fila deles continuam visíveis e aprovavéis
- Podem designar um **substituto** (outro gestor ou diretor ativo)
  que recebe as notas novas em nome deles

A regra é simétrica:

- Funcionário que tenta enviar para gestor indisponível e **sem
  substituto** vê erro claro: "Seu gestor está temporariamente
  indisponível e não designou substituto. Contate o admin."
- Mesmo cenário para diretor indisponível sem substituto.

O substituto precisa ter a **mesma role** (gestor substitui gestor,
diretor substitui diretor) e estar ativo. Substituto também
indisponível **não** cascateia — para evitar loop infinito de
delegação.

---

## Anexos

Cada nota tem entre **1 e 5 PDFs** anexados, com:

- Tamanho máximo de **10 MB por arquivo**
- Tamanho máximo total de **25 MB por nota**
- Validação de PDF com `pypdf` (rejeita arquivos corrompidos ou
  com formato inválido)
- Criptografia AES-256 (via Fernet) antes do upload ao R2
- Cada arquivo tem chave Fernet única, criptografada por sua vez
  com a `MASTER_ENCRYPTION_KEY` da aplicação

Detalhes técnicos em [security.md](security.md#criptografia-de-pdfs).

---

## Comentários (thread assíncrona)

Cada nota tem uma thread de comentários onde qualquer pessoa com
acesso à nota pode escrever. Comentários são:

- **Imutáveis**: não dá pra editar ou apagar depois de postar
  (protege a trilha de auditoria)
- **Limitados a 2000 caracteres** por mensagem
- **Paginados** (50 por página) para evitar carregamento pesado em
  threads longas

---

## Auditoria

Cada ação relevante gera um registro de auditoria com:

- Quem fez (`user_id`)
- O quê (`action`: LOGIN, CREATE_INVOICE, APPROVE, REJECT, etc)
- Em qual recurso (`resource_type` + `resource_id`)
- Quando (`timestamp`, sempre UTC)
- De onde (IP pseudonimizado via HMAC-SHA256 — LGPD)
- Por qual método HTTP
- User-Agent
- Se teve sucesso

**Hash chain**: cada registro guarda o hash do registro anterior
(`prev_hash`) + hash dele próprio (`row_hash`). Isso forma uma cadeia:
qualquer modificação retroativa quebra a cadeia. O admin pode validar
a integridade a qualquer momento via interface (verifica todos os
hashes em ordem).

Esse mecanismo defende contra um atacante (ou admin malicioso) que
consiga acesso direto ao banco e tente apagar/alterar registros para
encobrir ações.

---

## Verify público (rastreabilidade externa)

Cada comprovante final tem um QR Code que aponta para
`/verify/{invoice_id}`. Essa página é **pública** (sem login) e
mostra:

- Número da nota
- Status (Lançado/Aprovado/etc)
- Valor formatado
- Setor de origem
- Datas de emissão e vencimento
- Dados **mascarados** dos aprovadores: "João S****" em vez do nome
  completo
- CPF/CNPJ parcialmente oculto

Quando alguém com login na empresa abre a mesma página, o JavaScript
detecta a sessão ativa e revela automaticamente os dados completos —
sem flash de "primeiro mostra mascarado depois revela".

Esse mecanismo respeita LGPD: dados pessoais ficam visíveis só pra
quem tem direito de ver.

---

## Defesa contra admin malicioso (insider threat)

O sistema considera que o admin é o ponto mais sensível e implementa
três mecanismos de defesa:

### 1. SMTP só via variável de ambiente

A configuração de email do sistema (provedor, host, credenciais) **não**
fica no banco — vive apenas em variáveis de ambiente lidas no boot.
Um admin malicioso que invade a interface não consegue trocar o SMTP
para interceptar códigos de recuperação de senha de outros admins/diretores.

### 2. Janela de 24h para ações sensíveis

Ações destrutivas do admin (encerrar conta, criar outro admin/diretor)
**não** são imediatas. Ficam pendentes por 24h durante as quais outro
admin ou diretor pode vetar. Se ninguém objetar em 24h, a ação acontece
automaticamente.

### 3. Hash chain do audit_log

Já descrito acima. Mesmo com acesso direto ao Postgres, o admin
malicioso não consegue apagar/alterar audit_logs sem quebrar a
verificação de cadeia.

---

## LGPD em resumo

- **Minimização**: JWT tem só `sub` (user_id) e `role`. Nome e email
  ficam no banco, não no token.
- **Pseudonimização**: IPs em audit_log são HMAC-SHA256 com segredo
  do servidor — admin não consegue reverter o hash em IP real, mas
  consegue saber se duas ações vieram do mesmo IP.
- **Retenção**: notas reprovadas auto-deletam em 90 dias. Notas pagas
  ficam indefinidamente (CTN exige 5 anos mínimo para fins fiscais).
- **Direito de exclusão**: admin pode "encerrar" um usuário, o que
  substitui dados pessoais (nome, email) por valores neutros. Mantém
  a estrutura referencial dos audit_logs e histórico de aprovação.
- **Verify público mascarado**: dados sensíveis só aparecem para
  quem tem login válido.
- Página `/privacidade` documenta tudo isso para usuários finais.

---

## Onde isso vive no código

| Conceito | Arquivos principais |
|---|---|
| Roles | `app/models/users.py` (enum `UserRole`) |
| Estados da nota | `app/models/invoices.py` (enum `InvoiceStatus`) |
| Transições FSM | `app/services/invoice_service.py` |
| Aprovação | métodos `submit_invoice`, `manager_review`, `director_review`, `mark_paid` |
| Substituto | `app/routers/auth.py:/me/availability` + service em `_get_manager_for_user` / `_resolve_effective_director` |
| Histórico | `app/models/approval_history.py` |
| Auditoria | `app/models/audit_logs.py` (com hash chain em `attach_audit_chain_listener`) |
| Comentários | `app/models/invoice_comments.py` |
