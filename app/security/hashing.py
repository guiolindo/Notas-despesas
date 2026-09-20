import hashlib
import hmac

from passlib.context import CryptContext


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def pseudonymize_ip(ip: str | None) -> str | None:
    """LGPD: pseudonimiza o IP com HMAC-SHA256 antes de gravar no log de auditoria.
    Preserva correlacao (mesmo IP → mesmo hash) sem armazenar o dado bruto.

    SEC-11 (auditoria set/2026): antes reutilizava SECRET_KEY (mesma chave
    dos JWTs). Rotacionar a SECRET_KEY por razao de seguranca destruia a
    correlacao historica de todos os IPs. Agora prefere PSEUDONYM_KEY
    dedicada; fallback para SECRET_KEY apenas se nao configurada (mantem
    compatibilidade com deploys atuais).
    """
    if not ip:
        return None
    import os
    from app.config import settings

    key = os.getenv("PSEUDONYM_KEY") or settings.SECRET_KEY
    digest = hmac.new(
        key.encode() if isinstance(key, str) else key,
        ip.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]  # 16 hex chars = 64 bits, suficiente para correlacao
    return f"ip:{digest}"
