"""Observabilidade basica: request_id propagado por toda a request + logger
estruturado.

P1-7 da auditoria: antes nao existia correlacao entre logs. Em multi-worker
era impossivel juntar 'rota X falhou para user Y'. Agora:

- RequestIdMiddleware atribui um UUID curto por request e exporta em context
  var pra qualquer logger.info/error dentro do pipeline pegar.
- Header `X-Request-ID` na resposta — cliente pode mandar de volta no suporte
  ('me da o id da request que falhou').
- Honra X-Request-ID enviado pelo cliente (util pra tracing end-to-end com
  proxy/CDN), mas sempre sanitiza para [a-zA-Z0-9_-]{8,64} pra evitar
  log-injection.

O logger 'app' deve ser usado pelo codigo da aplicacao em vez de logging
diretamente. Ele anexa request_id automaticamente quando disponivel.
"""
from __future__ import annotations

import contextvars
import logging
import re
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request


# Context var: cada request tem seu proprio valor; corotinas paralelas
# nao se misturam.
_request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None,
)

_REQUEST_ID_HEADER = "X-Request-ID"
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


def current_request_id() -> str | None:
    """Devolve o id da request em curso (None fora de request)."""
    return _request_id_var.get()


class _RequestIdFilter(logging.Filter):
    """Anexa request_id em todo LogRecord. Permite que formatters incluam
    o campo (ex: '%(request_id)s'). Quando nao ha request, fica '-'."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = current_request_id() or "-"
        return True


def install_request_id_logging() -> logging.Logger:
    """Configura logger 'app' com formato estruturado simples e o filter
    de request_id. Idempotente — chamar varias vezes nao duplica handler."""
    logger = logging.getLogger("app")
    if getattr(logger, "_request_id_installed", False):
        return logger
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [req=%(request_id)s] %(name)s: %(message)s",
        )
    )
    handler.addFilter(_RequestIdFilter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger._request_id_installed = True  # type: ignore[attr-defined]

    # Tambem instala o filter no logger raiz pra que mensagens de libs
    # (sqlalchemy, uvicorn) consigam usar o campo request_id quando
    # algum handler externo formatar com ele.
    logging.getLogger().addFilter(_RequestIdFilter())
    return logger


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Cliente pode enviar id pra tracing (util com proxy). Caso contrario
        # geramos um curto (12 hex chars — suficiente pra correlacao manual).
        incoming = request.headers.get(_REQUEST_ID_HEADER)
        rid = incoming if incoming and _VALID_REQUEST_ID.match(incoming) else uuid.uuid4().hex[:12]
        token = _request_id_var.set(rid)

        # Instrumentacao leve de timing: util pra investigar lag
        # reportado pelo usuario (5s percebidos em acoes). Loga apenas
        # rotas autenticadas/operacionais (filtra /static e /health/live
        # pra nao poluir). Codex sugeriu no chat de coordenacao.
        #
        # IMPORTANTE: o reset do contextvar precisa acontecer DEPOIS do
        # logger.info, senao o _RequestIdFilter le current_request_id()
        # como None e o log sai com req=- — perde justamente a correlacao
        # que a instrumentacao quer prover. Bug sutil apontado por Codex
        # no review de c095b3f. Estrutura agora: try logica + finally
        # do reset garantido mesmo em excecao.
        import time as _time
        from logging import getLogger as _getLogger

        start_ns = _time.perf_counter_ns()
        path = request.url.path
        is_noisy = (
            path.startswith("/static")
            or path == "/health/live"
        )
        try:
            response = await call_next(request)
            elapsed_ms = (_time.perf_counter_ns() - start_ns) / 1_000_000.0
            # Adiciona Server-Timing header — DevTools mostra no waterfall.
            try:
                response.headers["Server-Timing"] = f"app;dur={elapsed_ms:.1f}"
            except Exception:  # noqa: BLE001
                pass
            response.headers[_REQUEST_ID_HEADER] = rid
            # Loga apenas requests "interessantes" (>= 200ms, ou nao-OK).
            # AQUI o contextvar ainda esta setado — req=<rid> aparece no log.
            if not is_noisy and (elapsed_ms >= 200 or response.status_code >= 400):
                _getLogger("app").info(
                    "%s %s -> %d in %.0fms",
                    request.method, path, response.status_code, elapsed_ms,
                )
            return response
        finally:
            _request_id_var.reset(token)
