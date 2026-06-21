import logging
import os
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
from app.middleware.security import (
    BodySizeLimitMiddleware,
    RateLimitMiddleware,
    SecurityHeadersMiddleware,
)


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
        static_dir / "js" / "offline.js",
        static_dir / "sw.js",
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

# Pentest jun/2026 (issue #SEC-1): /docs, /redoc, /openapi.json publicos em
# PROD vazam o mapa completo da API (73 endpoints, schemas, parametros) pra
# qualquer atacante. So devs locais precisam disso — em PROD desligamos. DEV
# continua com tudo pra documentacao do FastAPI funcionar.
_PROD = os.environ.get("ENVIRONMENT", "DEV").upper() == "PROD"

app = FastAPI(
    title="Economart - Aprovacao de Notas Fiscais",
    version="1.0.0",
    docs_url=None if _PROD else "/docs",
    redoc_url=None if _PROD else "/redoc",
    openapi_url=None if _PROD else "/openapi.json",
)

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


# Migracoes + bootstrap moveram-se para app/migrations.py em jun/2026 (139
# linhas que poluiam o entry-point do FastAPI). Aqui so importamos e
# chamamos abaixo, depois de _startup_failure ser conhecido.
from app.migrations import (
    ensure_admin_exists,
    purge_old_rejected_on_startup,
    run_schema_migrations,
)



# CRITICO: migrations PRIMEIRO, admin DEPOIS — invertido causa
# UndefinedColumn em colunas novas adicionadas ao modelo.
# Pulamos quando startup_security_failure ja sinalizou config invalida em
# PROD: middleware ja vai responder 503 em toda rota, nao queremos rodar
# DDL nem inserir admin contra um banco talvez nao configurado.
if _startup_failure is None:
    run_schema_migrations()
    ensure_admin_exists()
    purge_old_rejected_on_startup()


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
# BodySizeLimitMiddleware roda ANTES do rate limit (ordem invertida:
# o ultimo add_middleware fica mais perto da rota). Rejeita Content-Length
# absurdo antes de gastar CPU pra parsing/rate-limit lookup.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
# RequestIdMiddleware vem por ultimo (= executa por primeiro), pra que o id
# ja esteja disponivel quando os outros middlewares logarem.
app.add_middleware(RequestIdMiddleware)

# CORS — em PROD restringe ao dominio publico; em DEV aceita qualquer origem
# para facilitar testes locais (Vite, ngrok, etc.)
# _PROD ja definido no topo do arquivo.
_railway_url = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
_cors_origins = (
    [f"https://{_railway_url}"] if _PROD and _railway_url else ["*"]
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


# Endpoints de assets, health, e error handlers movidos para modulos
# proprios em jun/2026 (Fase 1.2). main.py so chama register():
from app import error_handlers, health, static_views
static_views.register(app, BASE_DIR, STATIC_VERSION, templates)
health.register(app)
error_handlers.register(app, templates)
