# Plano Tecnico: Split de `app/static/css/main.css`

## Objetivo

Dividir `app/static/css/main.css`, hoje com aproximadamente 1580 linhas, em arquivos menores sem quebrar a identidade visual, o layout responsivo ou a CSP.

## Estado Atual

O arquivo contem:

- Transicoes e barra de progresso.
- Tokens globais (`:root`).
- Layout base: sidebar, header, content.
- Componentes compartilhados: tabelas, botoes, formularios, badges, alerts, modal, toast.
- Telas especificas: login, dashboards, invoice detail/list/form, admin, finance, comentarios, drawer.
- Responsividade.

Ja existe `:focus-visible` para `.btn` em `main.css`, entao o item P2-4 provavelmente esta parcial/totalmente atendido. Deve ser validado visualmente antes de duplicar regra.

## Estrategia Segura

Manter `main.css` como agregador temporario usando `@import`, depois trocar os templates se necessario.

### Fase 1: Criar estrutura

```
app/static/css/
  main.css
  base/
    tokens.css
    reset.css
    layout.css
  components/
    buttons.css
    forms.css
    tables.css
    badges.css
    modals.css
    alerts.css
    toast.css
  pages/
    auth.css
    dashboard.css
    invoices.css
    review.css
    finance.css
    admin.css
    comments.css
    drawer.css
  utilities.css
  responsive.css
```

### Fase 2: Mover por menor risco

Ordem recomendada:

1. Tokens/reset/utilities.
2. Componentes atomicos: buttons, badges, forms.
3. Componentes estruturais: tables, modals, alerts, toast.
4. Paginas especificas: admin, comments, finance, review, invoices.
5. Layout e responsive por ultimo.

## Regras Anti Erro

- Nao alterar seletores durante o split. Primeiro commit deve ser apenas move.
- Preservar ordem de cascata.
- Nao misturar refactor visual com split.
- Comparar screenshots antes/depois em:
  - login
  - dashboard
  - invoices list
  - invoice detail com comentarios
  - admin/users
  - finance/queue
- Validar mobile em 390px e desktop em 1440px.

## Criterios de Aceite

- `main.css` final pode continuar existindo como agregador.
- Nenhum elemento muda de tamanho/posicao inesperadamente.
- `:focus-visible` continua visivel para botoes e links de navegacao.
- Nenhum `style=` novo em templates.
- CSP permanece sem necessidade de `script-src unsafe-inline`.

## Itens Relacionados da Auditoria

- P2-4: foco visivel em `.btn` (ja ha regra; validar contraste).
- P2-7: split de CSS.
- P2-14: tabelas com `caption`/`scope` podem exigir ajustes visuais para captions ocultos/visiveis.

## Sequencia de Commits

1. Criar estrutura e mover tokens/reset/utilities.
2. Mover componentes compartilhados.
3. Mover paginas especificas.
4. Ajustar imports e remover duplicacao.
5. Rodar QA visual completo.
