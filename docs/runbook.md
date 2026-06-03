# Runbook Operacional

## Escopo

Este runbook orienta operacao, diagnostico e resposta a incidentes do sistema Economart.

## Servicos Principais

- Aplicacao web: FastAPI + Gunicorn/Uvicorn.
- Banco: PostgreSQL em producao, SQLite em desenvolvimento.
- Storage de anexos: Cloudflare R2, fallback local somente em desenvolvimento.
- Email: SMTP ou Resend.

## Checks Rapidos

### Aplicacao esta viva

```powershell
Invoke-RestMethod http://localhost:7145/health
```

Esperado:

```json
{"status":"ok"}
```

### Login inicial local

- URL: `http://localhost:7145`
- Usuario: `admin@economart.com`
- Senha: `Admin@2024!`

Trocar senha no primeiro acesso.

## Variaveis Criticas

- `DATABASE_URL`
- `SECRET_KEY`
- `MASTER_ENCRYPTION_KEY`
- `ENVIRONMENT`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_ENDPOINT_URL`
- `R2_BUCKET_NAME`

Em producao, ausencia de `SECRET_KEY` ou `MASTER_ENCRYPTION_KEY` deve ser tratada como incidente de configuracao.

## Rotina de Deploy

1. Confirmar branch e commit.
2. Verificar variaveis de ambiente no Railway.
3. Rodar checks de sintaxe local:

```powershell
python -B -c "import ast,pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p)) for p in pathlib.Path('app').rglob('*.py')]"
node --check app\static\js\app.js
```

4. Fazer deploy.
5. Conferir `/health`.
6. Fazer login como admin.
7. Testar fluxo minimo:
   - criar usuario
   - criar nota rascunho
   - enviar nota
   - aprovar
   - gerar comprovante

## Incidentes Comuns

### Login falha para todos

Possiveis causas:

- `SECRET_KEY` mudou e tokens antigos ficaram invalidos.
- Banco indisponivel.
- Usuario admin bloqueado/inativo.
- Cookie `secure` ativo em ambiente HTTP local.

Acoes:

1. Verificar logs do servidor.
2. Verificar `DATABASE_URL`.
3. Verificar `ENVIRONMENT`.
4. Confirmar existencia de admin ativo no banco.

### Upload ou download de PDF falha

Possiveis causas:

- `MASTER_ENCRYPTION_KEY` ausente ou alterada.
- Credenciais R2 incorretas.
- Objeto removido do R2.
- Fallback local usado em producao.

Acoes:

1. Verificar variaveis `R2_*`.
2. Confirmar que `MASTER_ENCRYPTION_KEY` nao mudou desde o upload.
3. Conferir logs do `drive_service`.

### Emails nao chegam

Possiveis causas:

- SMTP/Resend desabilitado.
- Credencial criptografada com `MASTER_ENCRYPTION_KEY` antiga.
- Railway bloqueando SMTP tradicional.
- Remetente nao validado no Resend.

Acoes:

1. Abrir `/admin/smtp`.
2. Enviar email de teste.
3. Conferir logs `[email-*]`.
4. Preferir Resend em Railway.

### Nota presa aguardando gestor/diretor

Possiveis causas:

- Gestor/diretor desativado.
- Gestor perdeu role `MANAGER`.
- Diretor indisponivel.
- Setor mal configurado.

Acoes:

1. Verificar usuario responsavel na nota.
2. Verificar status e historico.
3. Reatribuir responsavel via fluxo administrativo quando existir.
4. Registrar ajuste manual em auditoria.

## Backup e Restauracao

### Banco

- Usar backup gerenciado do Railway/PostgreSQL.
- Testar restauracao em ambiente separado antes de aplicar em producao.

### PDFs

- R2 deve ter politica de retencao adequada.
- Nao rotacionar `MASTER_ENCRYPTION_KEY` sem plano de recriptografia.

## Observabilidade Minima Recomendada

- Request id por requisicao.
- Logs estruturados com metodo, path, status, duracao e user id quando autenticado.
- Health dividido em:
  - `/health/live`: processo vivo.
  - `/health/ready`: banco e configuracao essenciais OK.

## Procedimento de Incidente

1. Classificar severidade.
2. Preservar evidencias: logs, request id, usuario, nota, horario.
3. Mitigar: desativar usuario, pausar deploy, restaurar config ou rollback.
4. Comunicar impactados.
5. Registrar postmortem usando `docs/templates/postmortem.md`.

## Contatos

Preencher em producao:

- Responsavel tecnico:
- Responsavel financeiro:
- Responsavel LGPD:
- Infra/Railway:
- Cloudflare/R2:
