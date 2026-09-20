"""Middleware de idempotency-key para requisicoes de mutacao.

BE-06 (auditoria set/2026): antes, um duplo clique ou retry automatico
duplicava efeitos (criacao de nota, transicao FSM, comentario). A UI
manda cabecalho `Idempotency-Key` com UUID; o middleware serve a
resposta cacheada se a mesma chave aparecer de novo em curto tempo.

Escopo:
- Aplica so a POST/PUT/PATCH/DELETE em rotas /api/ e /auth/logout.
- Cache in-memory por processo (aceitavel MVP; upgrade futuro pra Redis).
- TTL de 60s — suficiente pra pegar retries de rede/duplo clique,
  curto o suficiente pra nao segurar memoria.
- Cache-hit responde 200 com o body original — nao reexecuta a rota.

Header no cliente:
    fetch('/api/invoices/', {
      method: 'POST',
      headers: { 'Idempotency-Key': crypto.randomUUID() },
      ...
    })

Se o cliente NAO manda a chave, comportamento normal (sem idempotencia).
"""
from __future__ import annotations

import time
import threading
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


_TTL_SECONDS = 60.0
_MAX_ENTRIES = 5000  # teto para nao crescer sem limite
_MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class _Entry:
    __slots__ = ("status", "body", "media_type", "content_encoding", "expires_at")

    def __init__(self, status, body, media_type, content_encoding, expires_at):
        self.status = status
        self.body = body
        self.media_type = media_type
        self.content_encoding = content_encoding
        self.expires_at = expires_at


_cache: dict[tuple[str, str], _Entry] = {}
_cache_lock = threading.Lock()


def _sweep_expired(now: float) -> None:
    if len(_cache) < _MAX_ENTRIES:
        return
    for k, e in list(_cache.items()):
        if e.expires_at < now:
            _cache.pop(k, None)


class IdempotencyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        if method not in _MUTATION_METHODS:
            return await call_next(request)
        path = request.url.path
        # Escopo restrito — nao mexer em telas HTML
        if not (path.startswith("/api/") or path == "/auth/logout"):
            return await call_next(request)
        key = request.headers.get("idempotency-key", "").strip()
        if not key or len(key) > 128:
            return await call_next(request)
        # Bucket por (user_id proxy via key + path)
        bucket = (key, path)
        now = time.monotonic()
        with _cache_lock:
            entry = _cache.get(bucket)
            if entry and entry.expires_at > now:
                headers = {"X-Idempotent-Replay": "true"}
                if entry.content_encoding:
                    headers["Content-Encoding"] = entry.content_encoding
                return Response(
                    content=entry.body,
                    status_code=entry.status,
                    media_type=entry.media_type or "application/json",
                    headers=headers,
                )

        response = await call_next(request)
        # So cacheia respostas de sucesso e client-errors — evita
        # segurar 500 transitorio.
        if 200 <= response.status_code < 500 and response.status_code != 401:
            body_iter = [chunk async for chunk in response.body_iterator]
            body = b"".join(body_iter)
            # Preserva content-encoding pra devolver corpo compativel no replay
            content_encoding = response.headers.get("content-encoding")
            with _cache_lock:
                _cache[bucket] = _Entry(
                    status=response.status_code,
                    body=body,
                    media_type=response.media_type,
                    content_encoding=content_encoding,
                    expires_at=now + _TTL_SECONDS,
                )
                _sweep_expired(now)
            return Response(
                content=body,
                status_code=response.status_code,
                media_type=response.media_type,
                headers=dict(response.headers),
            )
        return response
