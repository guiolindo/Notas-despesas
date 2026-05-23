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
    """
    is_postgres = engine.dialect.name == "postgresql"
    if is_postgres:
        migrations = [
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS source_port INTEGER",
            "ALTER TABLE audit_logs ADD COLUMN IF NOT EXISTS http_method VARCHAR(10)",
            "ALTER TABLE approval_history ADD COLUMN IF NOT EXISTS source_port INTEGER",
        ]
    else:
        migrations = [
            "ALTER TABLE audit_logs ADD COLUMN source_port INTEGER",
            "ALTER TABLE audit_logs ADD COLUMN http_method VARCHAR(10)",
            "ALTER TABLE approval_history ADD COLUMN source_port INTEGER",
        ]
    with engine.connect() as conn:
        for stmt in migrations:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # SQLite: coluna ja existe


_run_schema_migrations()
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
app.include_router(invoices.router, prefix="/invoices", tags=["Notas Fiscais"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["Notas Fiscais API"])


@app.get("/health")
def health():
    return {"status": "ok"}
