import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.config import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


rate_limit_buckets: dict[str, list[datetime]] = {}


@dataclass(frozen=True)
class RateLimitPolicy:
    name: str
    methods: frozenset[str]
    pattern: re.Pattern[str]
    max_requests: int
    window_seconds: int


RATE_LIMIT_POLICIES: tuple[RateLimitPolicy, ...] = (
    RateLimitPolicy(
        name="auth-login",
        methods=frozenset({"POST"}),
        pattern=re.compile(r"^/auth/login$"),
        max_requests=10,
        window_seconds=60,
    ),
    RateLimitPolicy(
        name="auth-forgot-password",
        methods=frozenset({"POST"}),
        pattern=re.compile(r"^/auth/forgot-password$"),
        max_requests=5,
        window_seconds=600,
    ),
    RateLimitPolicy(
        name="auth-reset-password",
        methods=frozenset({"POST"}),
        pattern=re.compile(r"^/auth/reset-password$"),
        max_requests=8,
        window_seconds=600,
    ),
    RateLimitPolicy(
        name="lookup-cnpj",
        methods=frozenset({"GET"}),
        pattern=re.compile(r"^/api/invoices/lookup-cnpj/[^/]+$"),
        max_requests=30,
        window_seconds=60,
    ),
    RateLimitPolicy(
        name="invoice-comments",
        methods=frozenset({"GET", "POST"}),
        pattern=re.compile(r"^/api/invoices/[^/]+/comments$"),
        max_requests=30,
        window_seconds=60,
    ),
)


def _client_ip(request: Request) -> str:
    """Identifica o cliente para rate limit.

    Em producao atras de proxy (Railway/nginx/etc.), o socket costuma ser do
    proxy. Nessa situacao usamos o primeiro IP de X-Forwarded-For, que e o
    cliente original na convencao HTTP. Em dev/local, evita confiar em header
    forjado por cliente direto.
    """
    if settings.ENVIRONMENT.upper() in {"PROD", "PRODUCTION"}:
        forwarded_for = request.headers.get("x-forwarded-for", "")
        first_hop = forwarded_for.split(",", 1)[0].strip()
        if first_hop:
            return first_hop[:64]
    return (request.client.host if request.client else "unknown")[:64]


def _matching_policy(request: Request) -> RateLimitPolicy | None:
    method = request.method.upper()
    path = request.url.path
    for policy in RATE_LIMIT_POLICIES:
        if method in policy.methods and policy.pattern.match(path):
            return policy
    return None


def _sweep_expired(now: datetime) -> None:
    """Remove buckets antigos para conter crescimento em ataque distribuido."""
    if len(rate_limit_buckets) < 1000:
        return
    oldest_window = now - timedelta(
        seconds=max(policy.window_seconds for policy in RATE_LIMIT_POLICIES)
    )
    expired = [
        key for key, timestamps in rate_limit_buckets.items()
        if not any(timestamp > oldest_window for timestamp in timestamps)
    ]
    for key in expired:
        del rate_limit_buckets[key]


# Limites de body por classe de rota. Pentest jun/2026 (#SEC-6) confirmou
# que uvicorn/starlette nao impoem teto nativo: atacante mandando 12 PDFs de
# 9MB (~110MB) gastava ~34s de CPU/memoria do servidor antes do limite
# "Maximo 5 arquivos" do router rejeitar, abrindo vetor de DoS por flooding.
# Estes limites cortam o request ANTES do parse de multipart.
#  - upload de invoice: 5 arquivos x 10MB + overhead = 55MB de teto
#  - JSON/forms simples: 1MB e generoso pra qualquer payload legitimo
MAX_UPLOAD_BODY_BYTES = 55 * 1024 * 1024
MAX_JSON_BODY_BYTES = 1 * 1024 * 1024

# Rotas que aceitam upload de arquivo (multipart) e portanto podem subir
# ate o teto generoso. Casa por prefixo + verbo.
_UPLOAD_ROUTES: tuple[tuple[str, str], ...] = (
    ("POST", "/api/invoices/"),
    ("PATCH", "/api/invoices/"),
    ("PUT", "/api/invoices/"),
)


def _is_upload_route(request: Request) -> bool:
    if request.method.upper() not in {"POST", "PATCH", "PUT"}:
        return False
    path = request.url.path
    return path.startswith("/api/invoices/") and "comments" not in path


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Le Content-Length declarado. Se ausente (chunked), o
        # parsing posterior do FastAPI ainda limita por arquivo
        # individualmente — DoS via streaming infinito e mitigado
        # pelo timeout do uvicorn.
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                size = int(cl)
            except ValueError:
                size = 0
            limit = MAX_UPLOAD_BODY_BYTES if _is_upload_route(request) else MAX_JSON_BODY_BYTES
            if size > limit:
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Corpo da requisicao excede o limite de "
                            f"{limit // (1024 * 1024)}MB."
                        )
                    },
                )
        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # Camera liberada para a propria origem (scanner QR em /contas-a-pagar/scanner).
        # Microfone e geolocalizacao seguem bloqueados.
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        # HSTS: força HTTPS por 1 ano (habilite apenas em producao com HTTPS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # CSP — script-src SEM unsafe-inline e a protecao critica contra XSS.
        # style-src 'unsafe-inline' e aceitavel (baixo risco) e necessario porque
        # varios templates usam style="..." inline para espacamento contextual.
        response.headers[
            "Content-Security-Policy"
        ] = (
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src https://fonts.gstatic.com; "
            "img-src 'self' data:; "
            # jsdelivr liberado APENAS para o jsQR usado em /contas-a-pagar/scanner.
            # Sem unsafe-inline — todo script ainda precisa vir de origem confiavel.
            "script-src 'self' https://cdn.jsdelivr.net; "
            "frame-src 'self' blob:; "
            "object-src 'none'; "
            "base-uri 'self'"
        )
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        policy = _matching_policy(request)
        if policy:
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=policy.window_seconds)
            ip = _client_ip(request)
            bucket_key = f"{policy.name}:{ip}"
            timestamps = [
                timestamp
                for timestamp in rate_limit_buckets.get(bucket_key, [])
                if timestamp > window_start
            ]
            if len(timestamps) >= policy.max_requests:
                rate_limit_buckets[bucket_key] = timestamps
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Muitas tentativas. Aguarde antes de tentar novamente."},
                    headers={
                        "Retry-After": str(policy.window_seconds),
                        "X-RateLimit-Limit": str(policy.max_requests),
                        "X-RateLimit-Window": str(policy.window_seconds),
                    },
                )
            timestamps.append(now)
            rate_limit_buckets[bucket_key] = timestamps
            _sweep_expired(now)

        return await call_next(request)
