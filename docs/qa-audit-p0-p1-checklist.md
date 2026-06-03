# Checklist de QA - Auditoria P0/P1

## Objetivo

Validar os ajustes criticos da auditoria antes de push/deploy, com foco em cenarios reais de uso na Economart.

Este checklist cobre os commits recentes:

- `302df81`: refresh token, print/mark-paid e 404 indistinguivel.
- `35f9600`: acessibilidade de tabelas, chips e controles.
- `cc7f610`: fail-fast de chaves, must_change_password backend e substituto de gestor.

## Preparacao

- Usar base de teste ou backup recente restaurado em ambiente separado.
- Criar usuarios ativos para cada perfil: Admin, Funcionario, Gestor, Diretor, Financeiro e Contas a Pagar.
- Criar ao menos uma nota com PDF anexado e outra sem anexo.
- Registrar hora inicial do teste para facilitar busca nos logs e auditoria.

## P0-1 Refresh Token e Troca de Senha

### Sessao expira apos troca de senha

1. Entrar como usuario comum em dois navegadores ou abas isoladas.
2. Em uma sessao, trocar a senha.
3. Na outra sessao, tentar chamar uma API autenticada.
4. Confirmar que a sessao antiga nao continua valida.
5. Confirmar que o cookie de refresh antigo nao emite novo access token.

Resultado esperado:

- API retorna 401 ou redireciona para login conforme o contexto.
- Usuario consegue entrar apenas com a senha nova.
- Nao ha loop infinito de refresh no frontend.

### Refresh normal continua funcionando

1. Entrar como usuario comum.
2. Aguardar o access token expirar ou simular chamada apos expiracao.
3. Confirmar que o refresh cookie valido renova a sessao.

Resultado esperado:

- Usuario permanece logado quando nao houve troca de senha.
- Nenhuma tela fica travada em carregamento.

## P0-2 Impressao e Lancamento Financeiro

### Preview nao altera status

1. Criar nota aprovada e ainda nao paga.
2. Abrir preview/impressao por GET.
3. Recarregar a nota e conferir status.

Resultado esperado:

- Status permanece `APROVADO`.
- Historico nao registra pagamento.
- Auditoria nao marca lancamento financeiro.

### Lancamento exige acao explicita

1. Como Financeiro, abrir nota `APROVADO`.
2. Acionar o fluxo de confirmar recebimento/lancamento.
3. Confirmar a acao quando o modal pedir.
4. Conferir status, historico e PDF gerado.

Resultado esperado:

- Status muda para `PAGO` apenas apos POST explicito.
- Historico registra quem lancou, data/hora e comentario do sistema.
- Repetir a acao em nota ja `PAGO` nao duplica transicao indevida.

## P1-2 Fail-Fast de Chaves em Producao

### Producao sem chaves seguras

1. Em ambiente de teste com `ENVIRONMENT=production`, remover ou enfraquecer `SECRET_KEY` ou `MASTER_ENCRYPTION_KEY`.
2. Subir a aplicacao.
3. Abrir qualquer rota HTML e uma rota API.

Resultado esperado:

- Sistema responde com tela estetica de erro operacional ou 503.
- Logs deixam claro qual configuracao critica falhou.
- A aplicacao nao opera parcialmente com criptografia/autenticacao insegura.

### Desenvolvimento segue desbloqueado

1. Em ambiente local/dev, usar configuracao minima.
2. Subir a aplicacao.

Resultado esperado:

- Ambiente dev nao fica bloqueado pelo fail-fast.
- Logs mostram warning, nao parada total.

## P1-6 Verificacao Full Indistinguivel

1. Acessar uma verificacao completa com usuario autorizado.
2. Acessar a mesma URL com usuario sem permissao.
3. Acessar uma URL inexistente.

Resultado esperado:

- Usuario autorizado ve detalhes permitidos.
- Usuario sem acesso recebe resposta indistinguivel de inexistente.
- A resposta nao revela se a nota existe.

## P1-8 Must Change Password no Backend

1. Admin marca usuario com `must_change_password`.
2. Usuario tenta acessar tela normal.
3. Usuario tenta chamar API diretamente via navegador/devtools/script.
4. Usuario troca a senha.
5. Usuario repete uma acao normal.

Resultado esperado:

- Backend bloqueia APIs nao permitidas com 428 enquanto a senha nao for trocada.
- Frontend leva o usuario para `/change-password`.
- Depois da troca, a navegacao volta ao normal.
- Endpoints essenciais para trocar senha e sair continuam funcionando.

## P1-9 Substituto de Gestor

### Gestor titular indisponivel com substituto ativo

1. Configurar funcionario com gestor titular.
2. Marcar gestor titular como indisponivel para notas.
3. Configurar substituto ativo com role adequada.
4. Funcionario envia uma nota.

Resultado esperado:

- Nota vai para o substituto.
- Historico/auditoria permitem entender o roteamento.
- Gestor titular nao recebe responsabilidade nova enquanto indisponivel.

### Gestor indisponivel sem substituto

1. Remover substituto ou desativar o substituto.
2. Funcionario tenta enviar nota.

Resultado esperado:

- Sistema bloqueia envio com mensagem clara.
- Nota nao fica em estado intermediario quebrado.

## Acessibilidade P2 Ja Aplicada

### Tabelas

1. Abrir dashboard, lista de notas, fila financeira, auditoria e usuarios.
2. Inspecionar com leitor de tela ou ferramenta de acessibilidade.

Resultado esperado:

- Tabelas possuem caption acessivel.
- Cabecalhos usam `scope="col"`.
- Coluna de acoes tem nome, nao cabecalho vazio.

### Controles de PDF e Comentarios

1. Abrir detalhe de nota com PDF.
2. Navegar por teclado nos controles de zoom, girar, tela cheia e abrir em nova aba.
3. Focar campo de comentario.

Resultado esperado:

- Controles iconicos possuem nome acessivel.
- Campo de comentario esta associado ao texto de ajuda.
- Foco visivel aparece nos botoes.

## Regressao Geral de Fluxo

Executar ao menos um ciclo completo:

1. Funcionario cria nota com PDF.
2. Envia para gestor.
3. Gestor aprova e encaminha ao diretor.
4. Diretor aprova.
5. Financeiro faz preview.
6. Financeiro marca como pago.
7. Verificar QR/public verify.
8. Conferir historico e auditoria.

Resultado esperado:

- Nenhuma etapa exige permissao indevida.
- Status evolui na ordem correta.
- PDF continua acessivel.
- Auditoria registra acoes sensiveis.

## Evidencias Para Guardar

- Hash do commit testado.
- Ambiente e variaveis relevantes, sem expor segredos.
- Usuario/perfil usado em cada teste.
- IDs das notas de teste.
- Screenshots apenas de telas sem dados sensiveis reais.
- Trechos de log com request id quando disponivel.

## Criterios de Bloqueio Para Deploy

- GET de preview altera status financeiro.
- Refresh antigo permanece valido apos troca de senha.
- Producao sobe com chaves padrao/inseguras.
- Usuario com `must_change_password` consegue operar APIs fora da troca de senha.
- Nota fica sem responsavel quando gestor esta indisponivel.
- Erro revela existencia de nota para usuario sem acesso.
