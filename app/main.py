import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jinja2 import select_autoescape
from sqlalchemy import text

from app import models
from app.config import startup_security_failure
from app.database import Base, engine
from app.middleware.observability import (
    RequestIdMiddleware,
    install_request_id_logging,
)
from app.middleware.security import RateLimitMiddleware, SecurityHeadersMiddleware


# Instala logger com request_id antes de qualquer log de startup — P1-7.
install_request_id_logging()


BASE_DIR = Path(__file__).resolve().parent

# Autoescape explícito (CVE-2024-22195 + prevenção XSS) — LGPD Art. 46
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.autoescape = select_autoescape(
    enabled_extensions=("html", "htm", "xml"),
    default_for_string=True,
)


def _compute_static_version() -> str:
    """Hash dos arquivos JS/CSS principais para cache-busting via ?v=...
    No deploy, qualquer mudanca neles muda a versao e força browsers a
    rebaixar. Antes deste mecanismo, Cache-Control:max-age=86400 segurava
    usuarios em versoes antigas por 24h apos deploy — causou bug reportado
    onde fix do login nao chegava ate o browser por estar em cache."""
    import hashlib

    static_dir = BASE_DIR / "static"
    # Arquivos que importam pra invalidacao: JS de modulo + CSS principal.
    files = [
        static_dir / "js" / "app.js",
        static_dir / "js" / "format.js",
        static_dir / "js" / "documents.js",
        static_dir / "js" / "comments.js",
        static_dir / "js" / "password.js",
        static_dir / "css" / "main.css",
    ]
    h = hashlib.sha256()
    for f in files:
        try:
            stat = f.stat()
            h.update(f.name.encode())
            h.update(str(stat.st_mtime_ns).encode())
            h.update(str(stat.st_size).encode())
        except OSError:
            continue
    return h.hexdigest()[:10]


STATIC_VERSION = _compute_static_version()
# Disponivel em todos os templates como {{ STATIC_VERSION }}.
templates.env.globals["STATIC_VERSION"] = STATIC_VERSION

app = FastAPI(title="Economart - Aprovacao de Notas Fiscais", version="1.0.0")

# P1-2 da auditoria: PROD nao pode subir com SECRET_KEY default ou
# MASTER_ENCRYPTION_KEY ausente. Em vez de stacktrace cru, qualquer rota
# devolve 503 + tela estetica enquanto as chaves nao forem definidas.
# Logamos um banner explicito no orquestrador pra alertar ops.
_startup_failure = startup_security_failure()
if _startup_failure is not None:
    _logger = logging.getLogger("uvicorn.error")
    _logger.critical("=" * 70)
    _logger.critical("ECONOMART NAO PODE SUBIR EM PROD: configuracao incompleta.")
    _logger.critical("Defina no ambiente: %s", ", ".join(_startup_failure.missing))
    _logger.critical("Toda rota responde 503 ate as chaves serem configuradas.")
    _logger.critical("=" * 70)


@app.middleware("http")
async def _intercept_startup_failure(request: Request, call_next):
    """Quando o app subiu em PROD sem secrets criticos, intercepta TODAS as
    requests e devolve a tela amigavel + 503. Excecoes: /static (a propria
    pagina precisa carregar) e /health/live (orquestrador precisa saber que
    o processo respira; readiness ja vai falhar pelos checks normais)."""
    path = request.url.path
    if (
        _startup_failure is None
        or path.startswith("/static")
        or path == "/health/live"
    ):
        return await call_next(request)
    # API recebe JSON com pista pra ops; navegacao recebe HTML.
    if request.url.path.startswith(("/api/", "/auth/")):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "Servico indisponivel. Configuracao incompleta.",
                "missing": _startup_failure.missing,
            },
        )
    html = templates.get_template("startup_error.html").render(
        missing=_startup_failure.missing,
    )
    return HTMLResponse(html, status_code=503)


# Se a config esta quebrada, evita rodar create_all e migrations contra um
# banco que pode nem estar acessivel — sair cedo deixa o middleware acima
# servir a tela mesmo sem DB up.
if _startup_failure is None:
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
# Pulamos quando startup_security_failure ja sinalizou config invalida em
# PROD: middleware ja vai responder 503 em toda rota, nao queremos rodar
# DDL nem inserir admin contra um banco talvez nao configurado.
if _startup_failure is None:
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


# P2-8 da auditoria: worker assincrono que drena email_queue. Roda dentro
# do proprio event loop do FastAPI/uvicorn. Em gunicorn -w N, cada worker
# inicia seu loop; o claim usa FOR UPDATE SKIP LOCKED no PG pra coordenar.
@app.on_event("startup")
async def _start_email_worker() -> None:
    if _startup_failure is not None:
        return
    try:
        from app.services.email_queue_service import start_background_worker
        start_background_worker(interval_seconds=15)
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).warning(f"[startup] email worker falhou ao subir: {exc}")


# Subclasse do StaticFiles que adiciona Cache-Control para reduzir
# revalidacao em cada request. Sem isso, usuario reportou app.js de 147KB
# carregando em ~1s a cada navegacao porque o browser tinha que validar
# 304 toda vez. Com Cache-Control:public, max-age=86400 o browser usa o
# cache local por 24h sem ida ao server.
#
# 24h e conservador — quando atualizarmos JS/CSS, usuarios em sessao ativa
# pegam o novo na proxima visita. Em deploy critico podemos disparar
# Ctrl+F5 no time. Cache mais agressivo (max-age=31536000 immutable) so
# faria sentido com hash no nome do arquivo (build pipeline), que ainda
# nao temos.
class _CachedStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers.setdefault("Cache-Control", "public, max-age=86400")
        return response


app.mount("/static", _CachedStaticFiles(directory=str(BASE_DIR / "static")), name="static")

# GZipMiddleware: comprime respostas >= 500 bytes. JS/HTML/JSON tipicamente
# reduzem 70% (147KB de app.js -> ~35KB transmitidos). Causa principal do
# lag percebido em cold start do Railway sem CDN. Adiciona Vary:
# Accept-Encoding automaticamente.
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)
# RequestIdMiddleware vem por ultimo (= executa por primeiro), pra que o id
# ja esteja disponivel quando os outros middlewares logarem.
app.add_middleware(RequestIdMiddleware)

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
    """Alias historico — equivalente a /health/live. Mantido pra orquestradores
    que ja apontam pra /health."""
    return {"status": "ok"}


@app.get("/health/live")
def health_live():
    """Liveness: processo respondendo. Nao toca DB nem R2 — orquestrador usa
    isso pra decidir 'reiniciar pod ou nao'. Falha aqui = matar o processo."""
    return {"status": "ok"}


@app.get("/health/ready")
def health_ready():
    """Readiness: app pronto pra receber trafego.

    Checa DB com um SELECT 1 com timeout curto. Falha aqui faz o orquestrador
    tirar o pod do round-robin SEM matar — quando o DB volta, o app volta
    automaticamente. Cobre P1-7 da auditoria (antes /health era so um echo).
    """
    from app.database import SessionLocal
    db_ok = False
    db_error: str | None = None
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
            db_ok = True
    except Exception as exc:  # noqa: BLE001
        db_error = str(exc)[:200]
    status_code = 200 if db_ok else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if db_ok else "not_ready",
            "checks": {"db": {"ok": db_ok, "error": db_error}},
        },
    )


@app.get("/health/dependencies")
def health_dependencies():
    """Best-effort: status detalhado de dependencias externas (DB, R2, email).

    Nao usar pra readiness — uma falha do R2 nao deveria tirar o app do
    trafego se a maior parte das rotas continua respondendo. Util pra
    dashboard de status manual.
    """
    from app.config import settings
    from app.database import SessionLocal

    checks: dict[str, dict] = {}

    # DB
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        checks["db"] = {"ok": True}
    except Exception as exc:  # noqa: BLE001
        checks["db"] = {"ok": False, "error": str(exc)[:200]}

    # R2 (so reportar configuracao — nao fazer round-trip aqui pra evitar
    # custo a cada call ao endpoint)
    r2_configured = bool(
        settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_BUCKET_NAME
    )
    checks["r2"] = {
        "ok": r2_configured,
        "fallback_local": not r2_configured,
    }

    # Email provider
    provider = (settings.EMAIL_PROVIDER or "").upper()
    if provider == "SMTP":
        checks["email"] = {"provider": "SMTP", "configured": bool(settings.SMTP_HOST)}
    elif provider == "RESEND":
        checks["email"] = {"provider": "RESEND", "configured": bool(settings.RESEND_API_KEY)}
    else:
        checks["email"] = {"provider": "DISABLED"}

    all_ok = all(c.get("ok", True) for c in checks.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "checks": checks,
    }


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
