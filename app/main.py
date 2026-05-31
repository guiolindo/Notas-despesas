from pathlib import Path

from fastapi import FastAPI, Request
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


# A chamada de _ensure_admin_exists() acontece APOS _run_schema_migrations()
# mais abaixo. Isso e critico — _ensure_admin faz db.query(User) que tenta
# selecionar TODAS as colunas (incluindo as novas como password_changed_at).
# Se rodar antes da migration, deploy quebra com UndefinedColumn em DB antigo.


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

        # Fase 3: novo role CONTAS_A_PAGAR (read-only + scanner QR).
        # No Postgres role e um TYPE ENUM — precisa ALTER TYPE ADD VALUE.
        # No SQLite o Enum vira VARCHAR e aceita qualquer string.
        pg("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'CONTAS_A_PAGAR'"),
    ]
    import logging as _logging
    _log = _logging.getLogger(__name__)
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


# CRITICO: migrations PRIMEIRO, admin DEPOIS — invertido causa
# UndefinedColumn em colunas novas adicionadas ao modelo.
_run_schema_migrations()
_ensure_admin_exists()


def _purge_old_rejected_on_startup() -> None:
    """Limpa notas reprovadas ha mais de 90 dias. Roda no boot.
    Best-effort — falha aqui nao impede o app de subir.
    """
    try:
        from app.database import SessionLocal
        from app.services.invoice_service import purge_old_rejected_invoices
        with SessionLocal() as db:
            n = purge_old_rejected_invoices(db)
            if n:
                import logging
                logging.getLogger(__name__).info(
                    f"[startup] purgeu {n} nota(s) reprovada(s) >90 dias"
                )
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"[startup] purge falhou: {exc}")


_purge_old_rejected_on_startup()


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
from app.routers import (
    alerts,
    auth,
    contas_a_pagar,
    invoices,
    pages,
    pending_actions,
    print_routes,
)

app.include_router(auth.router, prefix="/auth", tags=["Autenticacao"])
app.include_router(admin_router.router, tags=["Admin"])
app.include_router(alerts.router, prefix="/alerts", tags=["Alertas"])
app.include_router(print_routes.router, tags=["Impressao"])
app.include_router(pages.router, tags=["Paginas"])
app.include_router(invoices.router, prefix="/api/invoices", tags=["Notas Fiscais API"])
app.include_router(contas_a_pagar.router, tags=["Contas a Pagar"])
app.include_router(pending_actions.router, tags=["Acoes Pendentes"])


@app.get("/health")
def health():
    return {"status": "ok"}


# ─── 404 amigavel pra URLs digitadas erradas ─────────────────────────────
# Rotas de API (/api/, /auth/, /alerts/, /admin/, /health) continuam
# retornando JSON — frontend e curl precisam do contrato JSON. So URLs
# de navegacao (HTML) recebem o template com contagem regressiva +
# redirect pra /login ou /dashboard.
from starlette.exceptions import HTTPException as _StarletteHTTPException
from starlette.responses import JSONResponse as _JSONResponse


_API_PREFIXES = ("/api/", "/auth/", "/alerts/", "/admin/", "/health")


def _is_api_path(path: str) -> bool:
    return any(path.startswith(p) for p in _API_PREFIXES)


@app.exception_handler(404)
async def _not_found_handler(request: Request, exc):
    path = request.url.path
    if _is_api_path(path):
        # Mantem contrato JSON pras rotas de API
        return _JSONResponse(
            status_code=404,
            content={"detail": getattr(exc, "detail", "Recurso nao encontrado")},
        )
    # Navegacao web: template amigavel
    return templates.TemplateResponse(
        request, "404.html", status_code=404
    )


# Reaproveita o handler de 404 para HTTPException(status_code=404) lancada
# manualmente em rotas HTML (raro, mas evita regressao se acontecer).
@app.exception_handler(_StarletteHTTPException)
async def _http_exception_handler(request: Request, exc: _StarletteHTTPException):
    if exc.status_code == 404 and not _is_api_path(request.url.path):
        return templates.TemplateResponse(
            request, "404.html", status_code=404
        )
    # Para qualquer outra HTTPException, mantem comportamento padrao do FastAPI
    return _JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )
