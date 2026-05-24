"""Configuracao SMTP persistida no banco.

Apenas UM registro existe — o admin edita via UI. A senha eh criptografada
com Fernet/MASTER_ENCRYPTION_KEY (mesma chave dos PDFs).
"""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text

from app.database import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SmtpSettings(Base):
    """Configuracao de envio de email — suporta SMTP tradicional e HTTP API (Resend).

    'provider' determina qual caminho usar:
    - 'SMTP'   : usa smtp_host/port/user/password/use_tls (Gmail, Outlook, etc.)
    - 'RESEND' : usa smtp_password_enc como API key, ignora demais campos SMTP
    """
    __tablename__ = "smtp_settings"

    id = Column(Integer, primary_key=True, default=1)  # forca singleton
    provider = Column(String(20), nullable=False, default="SMTP")  # SMTP | RESEND
    smtp_host = Column(String(255), nullable=False, default="")
    smtp_port = Column(Integer, nullable=False, default=587)
    smtp_user = Column(String(255), nullable=False, default="")
    # SMTP: senha do app. RESEND: API key (re_...). Sempre criptografado com Fernet.
    smtp_password_enc = Column(Text, nullable=True)
    smtp_from_email = Column(String(255), nullable=False, default="")
    smtp_from_name = Column(String(255), nullable=False, default="Economart Notas")
    use_tls = Column(Boolean, nullable=False, default=True)
    enabled = Column(Boolean, nullable=False, default=False)
    updated_at = Column(DateTime, default=utc_now, nullable=False)
    updated_by_id = Column(String(36), ForeignKey("users.id"), nullable=True)


class PasswordResetCode(Base):
    """Codigo de 6 digitos para recuperacao de senha (TTL 15 min)."""
    __tablename__ = "password_reset_codes"

    id = Column(String(36), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    code_hash = Column(String(255), nullable=False)  # bcrypt do codigo
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    # Anti brute-force: invalida apos N tentativas erradas
    attempts = Column(Integer, default=0, nullable=False)
