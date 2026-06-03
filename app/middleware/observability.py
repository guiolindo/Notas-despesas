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
        try:
            response = await call_next(request)
        finally:
            _request_id_var.reset(token)
        response.headers[_REQUEST_ID_HEADER] = rid
        return response
