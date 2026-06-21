"""Health endpoints — registrados via `register(app)`.

Split do `app/main.py` (Fase 1.2 do plano-refactor-master).
Cobre:
  - /health (alias historico)
  - /health/live (liveness)
  - /health/ready (readiness — checa DB)
  - /health/dependencies (status detalhado; gated em PROD)
"""
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text


_PROD = os.environ.get("ENVIRONMENT", "DEV").upper() == "PROD"


def _require_admin_or_dev(request: Request) -> None:
    """Gate de endpoints sensiveis de observabilidade: em PROD exige
    Bearer de ADMIN; em DEV libera. Pentest jun/2026 (issue #SEC-3):
    /health/dependencies expunha publicamente quais providers de email/R2
    estavam configurados — info util pra atacante mapear superficie.
    """
    if not _PROD:
        return
    from app.security.dependencies import get_current_user
    from app.models import UserRole
    from app.database import SessionLocal

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Auth requerido")
    token = auth_header[7:].strip()
    with SessionLocal() as session:
        try:
            user = get_current_user(token=token, db=session)
        except Exception:
            raise HTTPException(status_code=401, detail="Token invalido")
        if user.role != UserRole.ADMIN:
            raise HTTPException(status_code=403, detail="Permissao insuficiente")


def register(app: FastAPI) -> None:
    """Registra os 4 endpoints de health no app."""

    @app.get("/health")
    def health():
        """Alias historico — equivalente a /health/live. Mantido pra
        orquestradores que ja apontam pra /health."""
        return {"status": "ok"}

    @app.get("/health/live")
    def health_live():
        """Liveness: processo respondendo. Nao toca DB nem R2 — orquestrador
        usa isso pra decidir 'reiniciar pod ou nao'. Falha aqui = matar o
        processo."""
        return {"status": "ok"}

    @app.get("/health/ready")
    def health_ready():
        """Readiness: app pronto pra receber trafego.

        Checa DB com um SELECT 1 com timeout curto. Falha aqui faz o
        orquestrador tirar o pod do round-robin SEM matar — quando o DB
        volta, o app volta automaticamente. Cobre P1-7 da auditoria.
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
    def health_dependencies(request: Request):
        """Best-effort: status detalhado de dependencias externas (DB, R2,
        email). Em PROD exige Bearer de ADMIN (#SEC-3). Em DEV liberado.
        """
        _require_admin_or_dev(request)
        from app.config import settings
        from app.database import SessionLocal

        checks: dict[str, dict] = {}

        try:
            with SessionLocal() as session:
                session.execute(text("SELECT 1"))
            checks["db"] = {"ok": True}
        except Exception as exc:  # noqa: BLE001
            checks["db"] = {"ok": False, "error": str(exc)[:200]}

        r2_configured = bool(
            settings.R2_ACCESS_KEY_ID
            and settings.R2_SECRET_ACCESS_KEY
            and settings.R2_BUCKET_NAME
        )
        checks["r2"] = {
            "ok": r2_configured,
            "fallback_local": not r2_configured,
        }

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
