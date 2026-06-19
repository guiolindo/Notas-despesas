# Operações — deploy, monitoring e troubleshooting

Este documento cobre o que acontece **depois** do código pronto:
como entregar em produção, como monitorar e o que fazer quando
algo dá errado.

## Deploy em produção

### Railway (atual)

O sistema está hospedado no [Railway](https://railway.app). O deploy
é automático: a cada `git push` para a branch `main` no GitHub, o
Railway detecta, faz build e sobe.

**Configuração mínima** no painel do Railway:

#### Variables (Environment)

| Variável | Valor | Notas |
|---|---|---|
| `ENVIRONMENT` | `PROD` | Ativa fail-fast de secrets, HSTS, etc |
| `DATABASE_URL` | `postgresql://...` | Plugin Postgres do Railway gera automaticamente |
| `SECRET_KEY` | `<64-char hex>` | Gerar com `python -c "import secrets; print(secrets.token_hex(64))"` |
| `MASTER_ENCRYPTION_KEY` | `<Fernet key>` | Gerar com `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `RAILWAY_PUBLIC_DOMAIN` | `seudominio.up.railway.app` | Railway preenche automaticamente |
| `R2_ACCESS_KEY_ID` | da Cloudflare | |
| `R2_SECRET_ACCESS_KEY` | da Cloudflare | Guardado como secret |
| `R2_ENDPOINT_URL` | `https://<account>.r2.cloudflarestorage.com` | |
| `R2_BUCKET_NAME` | `economart-prod` | Crie no painel Cloudflare antes |
| `EMAIL_PROVIDER` | `SMTP` ou `RESEND` | Resend recomendado para Railway Hobby |
| `SMTP_*` ou `RESEND_API_KEY` | conforme provedor | Ver detalhes abaixo |
| `TRUSTED_PROXIES` | `*` | Faz o rate-limit honrar X-Forwarded-For |
| `MAX_LOGIN_ATTEMPTS` | `5` | (default) |
| `LOGIN_BLOCK_MINUTES` | `10` | (default) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `60` | (default) |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | (default) |

#### Build & Run Command

O Railway detecta automaticamente como projeto Python e roda
`pip install -r requirements.txt`. O start command precisa ser
ajustado para usar gunicorn:

```
gunicorn app.main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT
```

Workers (`-w`):

- 2 workers: padrão razoável para tráfego baixo/médio
- 4 workers: se VPS tem 2+ vCPUs e tráfego cresceu
- Cuidado: cada worker tem seu próprio rate-limit em memória
  (multi-worker divide o limite efetivo)

#### Healthcheck

Configurar no painel Railway:

- Path: `/health/ready`
- Timeout: 5 segundos
- Restart on failure

`/health/ready` faz `SELECT 1` no banco. Se falhar, Railway
restarta o pod.

Para monitoria externa (UptimeRobot, etc) usar `/health/live`
(não toca DB, mais leve).

---

## Provedor de email

### Opção 1: SMTP

Para SMTP genérico (Gmail, Outlook, servidor próprio):

```
EMAIL_PROVIDER=SMTP
SMTP_HOST=smtp.seuservidor.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=usuario
SMTP_PASSWORD=senha
SMTP_FROM_EMAIL=nao-responda@empresa.com
SMTP_FROM_NAME=Economart
```

⚠️ **Railway Hobby** bloqueia conexões SMTP de saída na maioria dos
provedores como medida anti-spam. Use Resend.

### Opção 2: Resend (recomendado para Railway)

```
EMAIL_PROVIDER=RESEND
RESEND_API_KEY=re_xxxxxxxxxx
SMTP_FROM_EMAIL=nao-responda@seudominio.com
SMTP_FROM_NAME=Economart
```

Resend usa HTTP API (não SMTP) — funciona em qualquer ambiente.
3000 emails/mês gratuitos.

### Importante: SMTP só por env

A configuração de email **não** é editável pela UI do admin
(defesa contra admin malicioso interceptar códigos de reset).
Mudou de provedor? Trocar a variável no Railway e reiniciar.

---

## Cloudflare R2

Storage de PDFs. Equivalente ao S3 da Amazon.

### Criar o bucket

1. No painel da Cloudflare, R2 → Create bucket
2. Nome: `economart-prod` (ou outro de sua escolha)
3. Region: Auto
4. Gerar token de acesso (R2 → Manage R2 API Tokens):
   - Permissões: Object Read & Write
   - Bucket: o criado
   - Copiar Access Key ID e Secret Access Key
5. Anotar o endpoint:
   `https://<account-id>.r2.cloudflarestorage.com`

### Caso o R2 esteja indisponível

Em desenvolvimento, o `drive_service` cai automaticamente para
`uploads/` local quando as variáveis R2 estão vazias. Em produção,
isso é **perigoso**: o filesystem do container Railway é efêmero,
o pod reinicia e os arquivos somem.

**Em PROD**: configurar todas as variáveis R2_*. Se o R2 ficar
inacessível em runtime, novos uploads devem falhar de verdade,
não cair para local. Esse é um TODO documentado.

---

## Observabilidade

### Logs estruturados

Todos os logs têm o formato:

```
2026-06-03 20:30:15,123 [INFO] [req=abc123def456] app.email_queue: drain: sent=2 failed=0 retried=0
```

Campos:

- timestamp ISO
- level (INFO, WARNING, ERROR, CRITICAL)
- `[req=...]` — request_id da chamada que gerou o log
- logger name (ex: `app.email_queue`)
- mensagem

Para correlacionar problemas:

1. Usuário reporta erro com horário
2. Pegar `X-Request-ID` da resposta dele (devtools → Network → Headers)
3. `grep "req=<id>" railway-logs` mostra **todos** os logs daquela
   request, mesmo se passou por múltiplos workers

### Health checks em produção

- `GET /health/live`: orquestrador usa para liveness
- `GET /health/ready`: orquestrador usa para readiness (tira do
  load-balancer se falhar, sem matar o pod)
- `GET /health/dependencies`: dashboard manual para ver status
  do R2 e email

### Metrics

Não há `/metrics` Prometheus ainda. Roadmap. Para emergência, o
Railway tem painel de CPU/memória/network do pod.

### Sentry

Não configurado ainda. Roadmap. Para emergência, logs do Railway
mostram tudo.

---

## Troubleshooting

### Sistema não sobe

1. Checar logs do Railway. Procurar por:
   - `[migration]` warnings — normais em SQLite local, ignoráveis
     em PG (algumas migrations só fazem sentido em SQLite)
   - `ECONOMART NAO PODE SUBIR` — config inválida
2. Se vir tela 503 "Configuração de segurança incompleta": faltou
   `SECRET_KEY` ou `MASTER_ENCRYPTION_KEY`. Configurar no painel
   e restart
3. Se vir 502 sem chegar no app: erro de build. Checar logs de
   build no Railway

### Botões não respondem no frontend

Já aconteceu uma vez por race condition entre o `Auth.ensureToken()`
e o primeiro fetch. Hotfixes aplicados:

- `Auth` faz migração defensiva de sessões antigas
- Pre-warm de `/refresh` no topo do `core.js` (antes do DOMContentLoaded)
- `apiFetch` sempre tenta `ensureToken` se sem token

Se voltar a acontecer:

1. Ctrl+F5 (hard reload) para garantir que pegou os módulos JS novos
2. F12 → Console → ver primeiro erro vermelho
3. F12 → Application → Storage → Clear all → relogar
4. Se persistir, abrir issue com o erro do console

### Email não chega

1. Checar status no banco:
   ```sql
   SELECT to_email, status, attempts, last_error, next_retry_at
   FROM email_queue
   WHERE created_at > NOW() - INTERVAL '1 hour'
   ORDER BY created_at DESC;
   ```
2. Se `status=PENDING` com `attempts > 0` e `last_error` populado:
   provedor está falhando. Ver `last_error` para a causa
3. Se `status=FAILED`: esgotou retries. Reenfileirar manualmente:
   ```sql
   UPDATE email_queue
   SET status='PENDING', attempts=0, next_retry_at=NOW(),
       last_error=NULL
   WHERE id='<uuid>';
   ```
4. Se `status=SENT` mas usuário não recebeu: verificar spam,
   verificar configuração SPF/DKIM do remetente

### Login em loop / 401 imediato

Provavelmente um destes:

- `password_changed_at` no banco está no futuro (relógio
  dessincronizado). Comparar `SELECT NOW(), password_changed_at
  FROM users WHERE email='x'` e ajustar
- Cookie de refresh corrompido. Logout + relogar
- Browser bloqueando cookies third-party. Verificar configurações
  do navegador

### Nota não chega ao gestor

1. Confirmar `users.manager_id` do criador aponta para gestor
   válido (ativo, role=MANAGER)
2. Confirmar gestor não está `unavailable_for_notes=true` (se
   está, deve ter `substitute_manager_id`)
3. Confirmar criador não tem `submit_directly_to_director=true`
   (se tem, deve ter passado `director_id` no submit)

### Performance lenta nas listagens

1. Checar quantidade total: nota com 50k linhas + filtro amplo +
   `per_page=100` é pesado
2. Usar `?fields=light` no GET /api/invoices para desabilitar
   eager loading de anexos/histórico
3. Verificar índices: `SELECT * FROM pg_indexes WHERE tablename='invoices'`
   deve mostrar pelo menos `idx_invoices_status`,
   `idx_invoices_created_by`, etc

---

## Procedimentos comuns

### Trocar uma chave de criptografia (SECRET_KEY)

⚠️ Isso **invalida todas as sessões** ativas. Todos os usuários
precisarão logar de novo. Acceptable em incidente; não fazer por
manutenção rotineira.

1. Gerar nova: `python -c "import secrets; print(secrets.token_hex(64))"`
2. Atualizar `SECRET_KEY` no painel do Railway
3. Restart automático
4. Comunicar usuários que precisarão logar de novo

### Trocar MASTER_ENCRYPTION_KEY

⚠️ **Não trocar em produção sem migração**. Trocar essa chave torna
todos os PDFs anteriores **inacessíveis** (chaves Fernet de cada
arquivo foram criptografadas com a antiga).

Para fazer rotação real:

1. Manter chave antiga em `OLD_MASTER_ENCRYPTION_KEY`
2. Para cada `invoice_attachment`:
   - Decriptar `encryption_key_enc` com chave antiga
   - Criptografar com chave nova
   - Salvar
3. Quando todos os anexos migrados, remover `OLD_MASTER_*`

Esse procedimento não está implementado ainda. Roadmap.

### Backup manual do banco

```bash
# Pegar DATABASE_URL do Railway (Settings → Variables)
pg_dump $DATABASE_URL > backup-$(date +%F-%H%M).sql

# Comprimir + criptografar
gzip backup-*.sql
gpg --symmetric --cipher-algo AES256 backup-*.sql.gz

# Subir pra storage externo
# (R2 separado, S3, Drive, etc)
```

Roadmap: cron diário automatizado.

### Restore de backup

```bash
# Criar database vazio (ou usar plugin novo do Railway)
createdb economart_restored

# Restore
gunzip -c backup-2026-06-03.sql.gz | psql $DATABASE_URL_NOVO
```

### Reset de senha do admin

Se o admin esqueceu a senha **e** não tem outro admin para resetar:

1. Acessar banco diretamente (psql via Railway)
2. Gerar hash bcrypt da nova senha:
   ```python
   python -c "from passlib.hash import bcrypt; print(bcrypt.using(rounds=12).hash('NovaSenha123'))"
   ```
3. Aplicar:
   ```sql
   UPDATE users
   SET hashed_password = '<hash>',
       must_change_password = true,
       password_changed_at = NOW(),
       login_attempts = 0,
       blocked_until = NULL
   WHERE email = 'admin@economart.com';
   ```
4. Logar com a senha temporária. Sistema vai exigir troca imediata
   (`must_change_password=true`)

---

## Checklist pré-deploy

Antes de cada deploy não-trivial:

- [ ] `python -m pytest tests/ -q` passa (21 testes verdes)
- [ ] `for f in app/static/js/*.js; do node --check "$f"; done` sem erro
      (valida sintaxe dos 19 módulos vanilla)
- [ ] Diff revisado por outra pessoa (PR review)
- [ ] Variáveis de ambiente novas adicionadas ao painel
- [ ] Migrações backward-compatíveis (não removem coluna que
      código antigo ainda usa)
- [ ] Tag de versão criada se for release (`git tag v1.2.3`)

Para mudanças em auth, fluxo financeiro ou banco:

- [ ] Smoke test runtime: subir local, fazer login, criar nota,
      enviar, aprovar, lançar
- [ ] Backup do banco antes do deploy
- [ ] Janela de baixo tráfego se possível
- [ ] Plano de rollback documentado (qual commit voltar)

---

## Limites conhecidos

- Multi-worker do gunicorn: rate-limit em memória divide por
  worker. Hoje aceitável; roadmap migrar para Redis quando
  tráfego crescer
- Backup off-site: não automatizado. Risco em incidente
  catastrófico do Railway
- R2 sem versioning: delete acidental é definitivo
- Sem Sentry/observabilidade externa: depende dos logs do
  Railway
- Worker de email em memória: se a tabela `email_queue` ficar
  com 10k+ PENDING, o batch de 25 por ciclo pode atrasar
  envios. Recomendação: monitorar e aumentar batch ou
  rodar worker dedicado
