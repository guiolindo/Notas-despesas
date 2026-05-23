from datetime import datetime, timedelta, timezone

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


login_attempts_by_ip: dict[str, list[datetime]] = {}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        # HSTS: força HTTPS por 1 ano (habilite apenas em producao com HTTPS)
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers[
            "Content-Security-Policy"
        ] = "default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; script-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'"
        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/auth/login" and request.method.upper() == "POST":
            now = datetime.now(timezone.utc)
            window_start = now - timedelta(seconds=60)
            ip = request.client.host if request.client else "unknown"
            timestamps = [
                timestamp
                for timestamp in login_attempts_by_ip.get(ip, [])
                if timestamp > window_start
            ]
            if len(timestamps) >= 10:
                login_attempts_by_ip[ip] = timestamps
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Muitas tentativas. Aguarde 1 minuto."},
                )
            timestamps.append(now)
            login_attempts_by_ip[ip] = timestamps

        return await call_next(request)
