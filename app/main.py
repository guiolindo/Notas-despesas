from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import select_autoescape
from sqlalchemy import text

from app import models
from app.database import Base, engine
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware


BASE_DIR = Path(__file__).resolve().parent

# Autoescape explícito (CVE-2024-22195 + prevenção XSS) — LGPD Art. 46
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.autoescape = select_autoescape(
    enabled_extensions=("html", "htm", "xml"),
    default_for_string=True,
)

app = FastAPI(title="Economart - Aprovacao de Notas Fiscais", version="1.0.0")

Base.metadata.create_all(bind=engine)


def _ensure_admin_exists() -> None:
    """Cria o usuario admin padrao se o banco estiver vazio (primeiro deploy)."""
    from sqlalchemy.orm import Session
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


_ensure_admin_exists()


def _run_schema_migrations() -> None:
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
    ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # SQLite: coluna/indice ja existe


_run_schema_migrations()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)

# CORS — em PROD restringe ao dominio publico; em DEV aceita qualquer origem
# para facilitar testes locais (Vite, ngrok, etc.)
import os
_is_prod = (os.environ.get("ENVIRONMENT", "DEV").upper() == "PROD")
_railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
_cors_origins = (
    [f"https://{_railway_url}"] if _is_prod and _railway_url else ["*"]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import admin as admin_router
from app.routers import alerts, auth, invoices, pages, print_routes

app.include_router(auth.router, prefix="/auth", tags=["Autenticacao"])
app.include_router(admin_router.router, tags=["Admin"])
app.include_router(alerts.router, prefix="/alerts", tags=["Alertas"])
app.include_router(print_routes.router, tags=["Impressao"])
app.include_router(pages.router, tags=["Paginas"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["Notas Fiscais API"])


@app.get("/health")
def health():
    return {"status": "ok"}
