# Documentacao Economart

Esta pasta guarda documentos tecnicos e operacionais do sistema de aprovacao de notas fiscais da Economart.

## Documentos Operacionais

- [architecture.md](architecture.md): visao da arquitetura, camadas, fluxos principais e riscos tecnicos.
- [runbook.md](runbook.md): procedimentos de operacao, deploy, troubleshooting e resposta a incidentes.
- [qa-audit-p0-p1-checklist.md](qa-audit-p0-p1-checklist.md): checklist manual de regressao para os achados criticos da auditoria.
- [templates/postmortem.md](templates/postmortem.md): modelo para registrar incidentes e aprendizados.

## Auditoria e Implementacao

- [CHANGELOG-audit-2026-06.md](CHANGELOG-audit-2026-06.md): resumo dos commits da auditoria, riscos tratados e como testar.
- [../AUDITORIA_COMPLETA_ECONOMART.md](../AUDITORIA_COMPLETA_ECONOMART.md): relatorio completo da auditoria revisada.

## Planos Internos de Implementacao

Os documentos abaixo foram usados para orientar refactors sensiveis e reduzir risco durante a implementacao. Eles ficam separados dos documentos operacionais para nao poluir a leitura principal do projeto.

- [implementation-plans/plan-appjs-split.md](implementation-plans/plan-appjs-split.md): plano tecnico para dividir `app/static/js/app.js`.
- [implementation-plans/plan-css-split.md](implementation-plans/plan-css-split.md): plano tecnico para dividir `app/static/css/main.css`.

Quando um plano interno for totalmente executado e nao tiver mais valor pratico, ele pode ser arquivado ou removido em uma limpeza posterior.
