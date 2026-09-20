# Créditos

## Auditoria de segurança e qualidade — set/2026

As correções aplicadas nos commits `61c6916`, `7456b93`, `aba84d9`,
`2ae62b2` e `bf72860` (SEC-01/02/03/08/09/10/12/17/18/20, BE-02/03,
APP-01, FE-05, INFRA-01/02, QA-03) foram derivadas do relatório de
auditoria consolidada em [`AUDITORIA_TECNICA.md`](AUDITORIA_TECNICA.md),
que combina duas auditorias independentes:

- **Auditoria estática (60 achados exclusivos)** — revisão completa de
  código-fonte, banco de dados, schema, testes e infraestrutura.
- **Auditoria dinâmica — [Manus AI](https://manus.im/) (15 achados
  exclusivos, 19/08/2026)** — auditoria em ambiente executado
  (Ubuntu 24.04, Python 3.12, `127.0.0.1:7145`), com cobertura completa
  de UI por perfil, medição real de cobertura (`coverage`), inventário
  recursivo de rotas, e pentest não-destrutivo com PDFs adversariais.
  Achado crítico **SEC-20** (logout não revoga refresh cookie nem page
  guard) — a única descoberta que exigiu reprodução dinâmica com cookie
  copiado antes/depois do logout — é atribuído integralmente ao Manus.
  Outros achados exclusivos do Manus corrigidos neste merge:
  **APP-01** (DEV sem chave = HTTP 500), **FE-05** (verify autenticado
  quebrado por template incompleto), **QA-03** (pytest ausente em
  requirements), **DOC-01** (contratos de API divergentes).
- **Achados convergentes (3)** — identificados independentemente pelas
  duas: BE-03 (mark-paid duplicado), SEC-10 (fail-open no parse PDF),
  DB-02 (migrações SQLite tratadas como warnings).

Agradecimento formal ao Manus AI pela auditoria dinâmica cuidadosa e
pela documentação de evidências reproduzível.
