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
    """
    if not ip:
        return None
    # Importacao local para evitar importacao circular com config
    from app.config import settings

    digest = hmac.new(
        settings.SECRET_KEY.encode(),
        ip.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]  # 16 hex chars = 64 bits, suficiente para correlacao
    return f"ip:{digest}"
