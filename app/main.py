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


def _run_schema_migrations() -> None:
    """Adiciona colunas novas a tabelas existentes (seguro — ignora se ja existir)."""
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
                pass  # Coluna ja existe — ignorar


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
