"""Endpoints de assets nao versionados (SW + offline page).

Split do `app/main.py` (Fase 1.2). Registrados via `register(app, ...)`.
"""
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates


def register(app: FastAPI, base_dir: Path, static_version: str, templates: Jinja2Templates) -> None:
    """Registra /sw.js e /offline.html no app."""

    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        """Serve o Service Worker. Precisa de 2 cuidados especiais:

        1. Cache-Control: no-cache — sem isso, deploy novo nao atualiza o
           SW no browser do usuario por ate 24h. O conteudo do SW e que
           dispara a deteccao de "novo SW disponivel"; precisa ser sempre
           fresco.
        2. Service-Worker-Allowed: / — escopo padrao do SW e o diretorio
           de onde ele e servido. Como servimos de '/', podemos cobrir
           tudo.
        3. Placeholder __SW_VERSION__ substituido pelo STATIC_VERSION pra
           que mudancas em JS/CSS provoquem rotacao de cache no SW.
        """
        sw_path = base_dir / "static" / "sw.js"
        try:
            body = sw_path.read_text(encoding="utf-8")
        except OSError:
            return Response("// SW indisponivel", status_code=500, media_type="application/javascript")
        body = body.replace("__SW_VERSION__", static_version)
        return Response(
            content=body,
            media_type="application/javascript",
            headers={
                "Cache-Control": "no-cache",
                "Service-Worker-Allowed": "/",
            },
        )

    @app.get("/offline.html", include_in_schema=False)
    def offline_page(request: Request):
        """Pagina mostrada pelo SW quando o usuario tenta navegar sem
        internet e nao tem a pagina alvo em cache."""
        return templates.TemplateResponse(request, "offline.html")
