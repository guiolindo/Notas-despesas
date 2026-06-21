"""404 amigavel para URLs digitadas erradas + handler global de HTTPException.

Split do `app/main.py` (Fase 1.2). Registrado via `register(app, templates)`.

Estrategia: rotas de API (/api/, /auth/, /alerts/, /admin/, /health) mantem
contrato JSON. Rotas de navegacao HTML recebem template amigavel com
contagem regressiva + redirect inteligente (logado -> dashboard, anonimo
-> login).
"""
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from starlette.exceptions import HTTPException as _StarletteHTTPException
from starlette.responses import JSONResponse


_API_PREFIXES = ("/api/", "/auth/", "/alerts/", "/admin/", "/health")


def _is_api_path(path: str) -> bool:
    return any(path.startswith(p) for p in _API_PREFIXES)


def register(app: FastAPI, templates: Jinja2Templates) -> None:
    """Registra os handlers de 404 e HTTPException no app."""

    @app.exception_handler(404)
    async def _not_found_handler(request: Request, exc):
        path = request.url.path
        if _is_api_path(path):
            # Mantem contrato JSON pras rotas de API
            return JSONResponse(
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
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=getattr(exc, "headers", None),
        )
