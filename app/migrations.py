"""Migracoes de schema in-process + bootstrap de dados iniciais.

Extraido do `app/main.py` (jun/2026) que tinha 613 linhas — esta secao
sozinha era ~180 linhas (migrations + ensure_admin + purge no startup),
poluindo o entry-point do FastAPI.

Estrategia (deliberada): migrations rodam in-process no startup, sem
Alembic. Cada nova coluna adicionada ao modelo precisa de uma linha aqui;
caso contrario bancos antigos quebram com UndefinedColumn no proximo
deploy. PostgreSQL usa `IF NOT EXISTS` nativo; SQLite ignora o erro
silenciosamente em DEV. Adotar Alembic e roadmap (ver docs/decisoes-*.md).
"""
import logging
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import engine


_log = logging.getLogger(__name__)


# ─── Migracoes de schema ─────────────────────────────────────────────────────


def run_schema_migrations() -> None:
    """Adiciona colunas novas a tabelas existentes.
    PostgreSQL: usa IF NOT EXISTS (nativo).
    SQLite: tenta e ignora erro se ja existir (desenvolvimento local).

    IMPORTANTE: toda coluna nova adicionada ao modelo precisa entrar aqui
    senao bancos antigos quebram com UndefinedColumn no proximo deploy.
    """
    is_postgres = engine.dialect.name == "postgresql"
    pg = lambda s: s if is_postgres else s.replace(" IF NOT EXISTS", "")

    # INFRA-09 (auditoria set/2026): comandos exclusivos de PostgreSQL
    # (ALTER TYPE, CREATE EXTENSION, DROP COLUMN, indices funcionais) sao
    # separados. Em SQLite o loop pula silenciosamente com log info em
    # vez de warning — evita poluir o boot do DEV com "SQL falhou".
    def _pg_only(s: str) -> str:
        """Marca comando como PG-only. Em SQLite, retorna None (skip)."""
        return s if is_postgres else "-- skipped in sqlite: " + s

    migrations = [
        # Audit / historico — colunas de individualizacao NAT (LGPD)
        pg("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS source_port INTEGER"),
        pg("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS http_method VARCHAR(10)"),
        pg("ALTER TABLE approval_history ADD COLUMN IF NOT EXISTS source_port INTEGER"),

        # Users — colunas adicionadas pos schema inicial
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS department_id VARCHAR(36)"),
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS submit_directly_to_director BOOLEAN DEFAULT FALSE"),

        # Invoices — colunas pos schema inicial (rastro de impressao + financeiro)
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS finance_id VARCHAR(36)"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS print_drive_file_id VARCHAR(255)"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS printed_at TIMESTAMP"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS printed_by_id VARCHAR(36)"),

        # Cleanup: coluna legacy 'department' — PG-only (SQLite nao
        # suporta DROP COLUMN IF EXISTS; coluna orfa nao machuca em DEV).
        _pg_only("ALTER TABLE users DROP COLUMN IF EXISTS department"),

        # Indices para consultas frequentes
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_status ON invoices(status)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_created_by ON invoices(created_by_id)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_manager ON invoices(manager_id)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_director ON invoices(director_id)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_number ON invoices(invoice_number)"),
        pg("CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id)"),
        pg("CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_logs(timestamp)"),
        pg("CREATE INDEX IF NOT EXISTS idx_history_invoice ON approval_history(invoice_id)"),
        pg("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)"),
        pg("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active)"),

        # Password reset tokens (criados sob demanda)
        pg("CREATE INDEX IF NOT EXISTS idx_pwreset_user ON password_reset_codes(user_id)"),
        pg("ALTER TABLE password_reset_codes ADD COLUMN IF NOT EXISTS attempts INTEGER DEFAULT 0"),

        # Provedor de email (SMTP ou HTTP API tipo Resend)
        pg("ALTER TABLE smtp_settings ADD COLUMN IF NOT EXISTS provider VARCHAR(20) DEFAULT 'SMTP'"),

        # Invalidacao de JWT apos reset de senha — tokens emitidos antes
        # desse timestamp sao rejeitados (forca relogin)
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMP"),

        # Snapshot de descricao no momento da reprovacao — exige edicao real
        # antes de permitir reenvio
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS description_at_rejection TEXT"),

        # Auto-pausa de recebimento de notas (ferias do diretor)
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS unavailable_for_notes BOOLEAN DEFAULT FALSE"),

        # CPF/CNPJ do fornecedor da nota + dados autopreenchidos pela API
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_document VARCHAR(14)"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_document_type VARCHAR(4)"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_name VARCHAR(255)"),
        pg("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS supplier_legal_name VARCHAR(255)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_supplier_doc ON invoices(supplier_document)"),

        # Hash chain dos audit_logs (deteccao de edicao retroativa)
        pg("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS prev_hash VARCHAR(64)"),
        pg("ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS row_hash VARCHAR(64)"),

        # Pending actions: quem executou via confirmacao antecipada
        pg("ALTER TABLE pending_admin_actions ADD COLUMN IF NOT EXISTS executed_by_id VARCHAR(36)"),

        # Repasse de nota entre diretores: novo valor no enum approvalaction
        _pg_only("ALTER TYPE approvalaction ADD VALUE IF NOT EXISTS 'TRANSFERRED_DIRECTOR'"),

        # Substituto durante ferias (delegacao automatica de notas)
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS substitute_director_id VARCHAR(36)"),
        # Mesmo conceito para MANAGER — fechou o gap apontado pela auditoria P1-9
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS substitute_manager_id VARCHAR(36)"),

        # Extensao unaccent: PG-only (SQLite nao tem sistema de extensoes).
        _pg_only("CREATE EXTENSION IF NOT EXISTS unaccent"),

        # Indices funcionais so em PG (SQLite nao aceita expressao no CREATE INDEX pre-3.9).
        _pg_only("CREATE INDEX IF NOT EXISTS idx_invoices_supplier_name_un ON invoices (LOWER(supplier_name))"),
        _pg_only("CREATE INDEX IF NOT EXISTS idx_invoices_description_un ON invoices (LOWER(description))"),
        # DB-08 (auditoria set/2026): consultas reais usam padroes compostos.
        # Alertas: status + due_date. Audit chain: timestamp+id descending.
        # Comentarios: por invoice_id.
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_status_due ON invoices(status, due_date)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_status_issue ON invoices(status, issue_date)"),
        pg("CREATE INDEX IF NOT EXISTS idx_audit_ts_id ON audit_logs(timestamp DESC, id DESC)"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoice_comments_invoice ON invoice_comments(invoice_id)"),

        # Fase 3: novo role CONTAS_A_PAGAR — PG-only ALTER TYPE.
        # SQLite: enum vira VARCHAR e aceita qualquer valor automaticamente.
        _pg_only("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'CONTAS_A_PAGAR'"),

        # Pentest jun/2026 (#SEC-5): logout passa a invalidar access tokens
        # emitidos antes do logout — sem isso, /auth/logout so apagava o
        # cookie refresh, deixando o access valido por ate 1h.
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_invalidated_at TIMESTAMP"),
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            # INFRA-09: comandos marcados como PG-only ficam como
            # comentario SQL em SQLite. Pulamos sem log ruidoso.
            if stmt.startswith("-- skipped in sqlite:"):
                _log.debug("[migration] pulado em sqlite: %s", stmt[22:80])
                continue
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as _exc:
                msg = str(_exc).lower()
                if ("already exists" in msg or "duplicate column" in msg
                        or "duplicate object" in msg):
                    continue
                _log.warning("[migration] '%s' falhou: %s", stmt[:60], _exc)


# ─── Bootstrap de dados iniciais ─────────────────────────────────────────────


def ensure_admin_exists() -> None:
    """Cria o usuario admin padrao se o banco estiver vazio (primeiro deploy).

    CRITICO: chamar APOS run_schema_migrations(). _ensure_admin faz
    db.query(User) que tenta selecionar TODAS as colunas (incluindo as novas
    como password_changed_at). Se rodar antes da migration, deploy quebra
    com UndefinedColumn em DB antigo.

    SEC-01 (auditoria set/2026): credencial NAO e mais hardcoded. Requer
    variaveis de ambiente BOOTSTRAP_ADMIN_EMAIL + BOOTSTRAP_ADMIN_PASSWORD.
    Sem elas:
     - DEV: gera senha aleatoria e loga UMA VEZ no stdout (com banner).
       Onboarding local nao trava, mas a senha nao esta versionada.
     - PROD: log ERROR e NAO cria admin — operador precisa provisionar
       manualmente via variaveis. Impede que uma nova instancia suba com
       credencial conhecida.
    """
    import logging
    import os
    import secrets
    from sqlalchemy.exc import IntegrityError
    from app.config import settings
    from app.models import User, UserRole
    from app.security.hashing import hash_password

    log = logging.getLogger("app.bootstrap")
    is_prod = (settings.ENVIRONMENT or "DEV").upper() == "PROD"

    with Session(engine) as db:
        if db.query(User).count() > 0:
            return

        email = (os.getenv("BOOTSTRAP_ADMIN_EMAIL") or "").strip().lower()
        password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD") or ""

        if not email or not password:
            if is_prod:
                log.error(
                    "[bootstrap] Banco vazio em PROD e BOOTSTRAP_ADMIN_EMAIL/"
                    "BOOTSTRAP_ADMIN_PASSWORD nao definidos. Admin NAO foi "
                    "criado. Defina as variaveis e reinicie."
                )
                return
            # DEV: gera senha aleatoria e imprime uma vez.
            email = email or "admin@economart.local"
            password = "Adm-" + secrets.token_urlsafe(12)
            log.warning(
                "\n\n%s\n[bootstrap DEV] Admin criado com credencial gerada:\n"
                "  email:    %s\n  password: %s\n"
                "Guarde agora — nao sera exibida de novo. Configure "
                "BOOTSTRAP_ADMIN_* no .env para credencial fixa.\n%s\n",
                "=" * 72, email, password, "=" * 72,
            )

        try:
            admin = User(
                name="Administrador",
                email=email,
                hashed_password=hash_password(password),
                role=UserRole.ADMIN,
                must_change_password=True,
                is_active=True,
            )
            db.add(admin)
            db.commit()
        except IntegrityError:
            db.rollback()  # outro worker ja criou — ignorar


_PURGE_LOCK_ID = 748291307  # adjacente ao lock da hash chain


def purge_old_rejected_on_startup() -> None:
    """Limpa notas reprovadas ha mais de 90 dias. Roda no boot.

    DB-07 (auditoria set/2026): antes, cada worker gunicorn executava
    a purga concorrentemente no startup — 2 workers apagando o mesmo
    conjunto criam erros de FK e deixam arquivos orfaos no R2. Agora
    tenta adquirir pg_try_advisory_lock — quem pegar executa, os
    outros pulam silenciosamente. SQLite (single-writer) roda sempre.

    Best-effort — falha aqui nao impede o app de subir.
    """
    try:
        from sqlalchemy import text as _sql_text
        from app.database import SessionLocal, engine as _engine
        from app.services.invoice_service import purge_old_rejected_invoices
        with SessionLocal() as db:
            if _engine.dialect.name == "postgresql":
                got = db.execute(
                    _sql_text("SELECT pg_try_advisory_lock(:k)"),
                    {"k": _PURGE_LOCK_ID},
                ).scalar()
                if not got:
                    _log.info("[startup] purge pulado — outro worker esta rodando")
                    return
                try:
                    n = purge_old_rejected_invoices(db)
                    if n:
                        _log.info(f"[startup] purgeu {n} nota(s) reprovada(s) >90 dias")
                finally:
                    db.execute(
                        _sql_text("SELECT pg_advisory_unlock(:k)"),
                        {"k": _PURGE_LOCK_ID},
                    )
            else:
                n = purge_old_rejected_invoices(db)
                if n:
                    _log.info(f"[startup] purgeu {n} nota(s) reprovada(s) >90 dias")
    except Exception as exc:  # noqa: BLE001
        _log.warning(f"[startup] purge falhou: {exc}")
