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

        # Cleanup: coluna legacy 'department' (string) substituida por
        # department_id (FK). DROP COLUMN IF EXISTS so no Postgres; SQLite
        # nao suporta, mas em dev nao machuca deixar a coluna orfa.
        pg("ALTER TABLE users DROP COLUMN IF EXISTS department"),

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
        pg("ALTER TYPE approvalaction ADD VALUE IF NOT EXISTS 'TRANSFERRED_DIRECTOR'"),

        # Substituto durante ferias (delegacao automatica de notas)
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS substitute_director_id VARCHAR(36)"),
        # Mesmo conceito para MANAGER — fechou o gap apontado pela auditoria P1-9
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS substitute_manager_id VARCHAR(36)"),

        # Extensao unaccent: busca acento-insensivel em descricao/fornecedor.
        # Sem isso 'escritorio' nao acha 'escritório'. SQLite ignora (cai
        # em lower() simples no fallback do servico).
        pg("CREATE EXTENSION IF NOT EXISTS unaccent"),

        # Indices funcionais para acelerar a busca textual em PG
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_supplier_name_un ON invoices (LOWER(supplier_name))"),
        pg("CREATE INDEX IF NOT EXISTS idx_invoices_description_un ON invoices (LOWER(description))"),

        # Fase 3: novo role CONTAS_A_PAGAR (read-only + scanner QR).
        # No Postgres role e um TYPE ENUM — precisa ALTER TYPE ADD VALUE.
        # No SQLite o Enum vira VARCHAR e aceita qualquer string.
        pg("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'CONTAS_A_PAGAR'"),

        # Pentest jun/2026 (#SEC-5): logout passa a invalidar access tokens
        # emitidos antes do logout — sem isso, /auth/logout so apagava o
        # cookie refresh, deixando o access valido por ate 1h.
        pg("ALTER TABLE users ADD COLUMN IF NOT EXISTS session_invalidated_at TIMESTAMP"),
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception as _exc:
                # SQLite: coluna/indice ja existe (esperado). Mas se for outro
                # tipo de erro em PG, queremos pelo menos um aviso no log.
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

    SEC-roadmap jun/2026: a senha default `Admin@2024!` esta hardcoded
    pra facilitar bootstrap. `must_change_password=True` forca a troca
    no primeiro login e desde jun/2026 trocar pela mesma senha e rejeitado
    com 422 (SEC-8). Em PROD, trocar imediatamente apos primeiro acesso.
    """
    from sqlalchemy.exc import IntegrityError
    from app.models import User, UserRole
    from app.security.hashing import hash_password

    with Session(engine) as db:
        if db.query(User).count() == 0:
            try:
                admin = User(
                    name="Administrador",
                    email="admin@economart.com",
                    hashed_password=hash_password("Admin@2024!"),
                    role=UserRole.ADMIN,
                    must_change_password=True,
                    is_active=True,
                )
                db.add(admin)
                db.commit()
            except IntegrityError:
                db.rollback()  # outro worker ja criou — ignorar


def purge_old_rejected_on_startup() -> None:
    """Limpa notas reprovadas ha mais de 90 dias. Roda no boot.

    Best-effort — falha aqui nao impede o app de subir.
    """
    try:
        from app.database import SessionLocal
        from app.services.invoice_service import purge_old_rejected_invoices
        with SessionLocal() as db:
            n = purge_old_rejected_invoices(db)
            if n:
                _log.info(f"[startup] purgeu {n} nota(s) reprovada(s) >90 dias")
    except Exception as exc:  # noqa: BLE001
        _log.warning(f"[startup] purge falhou: {exc}")
