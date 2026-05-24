"""Servico de envio de emails via SMTP configuravel pelo admin.

A senha SMTP eh persistida criptografada com Fernet/MASTER_ENCRYPTION_KEY.
Envios sao defensivos: erro de SMTP NUNCA quebra o fluxo principal —
apenas loga e segue, evitando que email caido impeca aprovacao de notas.
"""
from __future__ import annotations

import base64
import json
import logging
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session

from app.config import settings
from app.models import SmtpSettings


logger = logging.getLogger(__name__)


def _master_key() -> bytes:
    key = settings.MASTER_ENCRYPTION_KEY
    if isinstance(key, str):
        key = key.strip().encode("utf-8")
    Fernet(key)  # valida formato
    return key


def encrypt_password(plain: str) -> str:
    encrypted = Fernet(_master_key()).encrypt(plain.encode("utf-8"))
    return base64.urlsafe_b64encode(encrypted).decode("ascii")


def decrypt_password(encrypted_b64: str) -> str:
    encrypted = base64.urlsafe_b64decode(encrypted_b64.encode("ascii"))
    return Fernet(_master_key()).decrypt(encrypted).decode("utf-8")


def get_smtp_settings(db: Session) -> Optional[SmtpSettings]:
    return db.query(SmtpSettings).first()


def _build_message(
    from_email: str,
    from_name: str,
    to_email: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Reply-To"] = "noreply@economart.local"
    msg["X-Auto-Response-Suppress"] = "All"
    # Texto plano como fallback
    text_part = text or "Esta mensagem requer um cliente que renderize HTML."
    msg.attach(MIMEText(text_part, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_email(
    db: Session,
    to_email: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> bool:
    """Envia email via provider configurado (SMTP ou Resend). Best-effort."""
    cfg = get_smtp_settings(db)
    if not cfg or not cfg.enabled:
        logger.info(f"[email] desabilitado — pulando envio para {to_email}")
        return False
    if not cfg.smtp_password_enc:
        logger.warning("[email] habilitado mas sem credencial (senha/API key)")
        return False

    try:
        secret = decrypt_password(cfg.smtp_password_enc)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[email] falha ao descriptografar credencial: {exc}")
        return False

    provider = (cfg.provider or "SMTP").upper()
    if provider == "RESEND":
        return _send_via_resend(cfg, secret, to_email, subject, html, text)
    return _send_via_smtp(cfg, secret, to_email, subject, html, text)


def _send_via_smtp(cfg, password, to_email, subject, html, text):
    if not cfg.smtp_host or not cfg.smtp_user:
        logger.warning("[email] SMTP sem host ou usuario configurado")
        return False
    msg = _build_message(
        cfg.smtp_from_email or cfg.smtp_user,
        cfg.smtp_from_name or "Economart",
        to_email, subject, html, text,
    )
    try:
        if cfg.use_tls:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                server.login(cfg.smtp_user, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=15) as server:
                server.login(cfg.smtp_user, password)
                server.send_message(msg)
        logger.info(f"[email-smtp] enviado para {to_email}: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[email-smtp] falha para {to_email}: {exc}")
        return False


def _send_via_resend(cfg, api_key, to_email, subject, html, text):
    """Envia via Resend HTTP API. Funciona em Railway (sem bloqueio SMTP)."""
    from_email = cfg.smtp_from_email or "onboarding@resend.dev"
    from_name = cfg.smtp_from_name or "Economart"
    payload = {
        "from": f"{from_name} <{from_email}>",
        "to": [to_email],
        "subject": subject,
        "html": html,
        "text": text or "Esta mensagem requer um cliente que renderize HTML.",
        "headers": {
            "X-Auto-Response-Suppress": "All",
            "Reply-To": "noreply@economart.local",
        },
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=data,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            logger.info(f"[email-resend] enviado para {to_email}: {subject} ({resp.status})")
            return True
    except urllib.error.HTTPError as exc:
        try:
            err_body = exc.read().decode("utf-8")
        except Exception:  # noqa: BLE001
            err_body = "(sem corpo)"
        logger.error(f"[email-resend] HTTP {exc.code} para {to_email}: {err_body}")
        return False
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[email-resend] falha para {to_email}: {exc}")
        return False


def send_email_async(
    to_email: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> None:
    """Envia email em thread daemon — request retorna sem esperar SMTP.

    Trade-off: se o worker do gunicorn reiniciar durante o envio, o email
    se perde. Para notificacoes de transicao de nota isso e aceitavel
    (proxima transicao ainda dispara um novo email). Para dados criticos
    (recuperacao de senha), usar BackgroundTasks do FastAPI no endpoint.
    """
    def _worker():
        from app.database import SessionLocal
        try:
            with SessionLocal() as session:
                send_email(session, to_email, subject, html, text)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[email-async] worker falhou para {to_email}: {exc}")

    threading.Thread(target=_worker, daemon=True, name=f"email-{to_email[:20]}").start()


# ─── Templates ─────────────────────────────────────────────────────────────

_BASE_STYLE = """
  body{font-family:Arial,Helvetica,sans-serif;background:#f4f5f7;color:#1f2937;margin:0;padding:24px}
  .card{max-width:520px;margin:0 auto;background:#fff;border-radius:8px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.05)}
  .brand{color:#FF6B00;font-size:20px;font-weight:700;margin-bottom:8px}
  h1{font-size:18px;margin:8px 0 16px 0}
  p{line-height:1.6;margin:8px 0}
  .meta{background:#f9fafb;border-radius:6px;padding:12px;margin:12px 0}
  .meta strong{color:#1e3a8a}
  .btn{display:inline-block;background:#FF6B00;color:#fff!important;padding:10px 18px;text-decoration:none;border-radius:6px;margin-top:12px;font-weight:600}
  .footer{margin-top:20px;font-size:12px;color:#6b7280;text-align:center}
"""


def _wrap(content: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{_BASE_STYLE}</style></head><body><div class="card"><div class="brand">ECONOMART</div>{content}<div class="footer">Esta e uma mensagem automatica. Por favor nao responda.</div></div></body></html>"""


def template_new_invoice_for_approver(
    approver_name: str,
    creator_name: str,
    invoice_number: str,
    amount: str,
    public_url: str,
) -> tuple[str, str, str]:
    subject = f"Nova nota fiscal aguardando sua aprovacao - {invoice_number}"
    html = _wrap(f"""
      <h1>Ola, {approver_name}</h1>
      <p>Uma nova nota fiscal foi enviada para sua aprovacao.</p>
      <div class="meta">
        <p><strong>Numero:</strong> {invoice_number}</p>
        <p><strong>Valor:</strong> {amount}</p>
        <p><strong>Criada por:</strong> {creator_name}</p>
      </div>
      <a class="btn" href="{public_url}">Abrir no sistema</a>
    """)
    text = f"Nova nota {invoice_number} ({amount}) criada por {creator_name} aguarda sua aprovacao.\n{public_url}"
    return subject, html, text


def template_invoice_rejected(
    creator_name: str,
    invoice_number: str,
    rejected_by: str,
    reason: str,
    public_url: str,
) -> tuple[str, str, str]:
    subject = f"Sua nota {invoice_number} foi reprovada"
    html = _wrap(f"""
      <h1>Ola, {creator_name}</h1>
      <p>Sua nota fiscal <strong>{invoice_number}</strong> foi reprovada por <strong>{rejected_by}</strong>.</p>
      <div class="meta">
        <p><strong>Motivo:</strong> {reason or '(nao informado)'}</p>
      </div>
      <p>Voce pode editar e reenviar a nota a qualquer momento.</p>
      <a class="btn" href="{public_url}">Abrir no sistema</a>
    """)
    text = f"Sua nota {invoice_number} foi reprovada por {rejected_by}.\nMotivo: {reason}\n{public_url}"
    return subject, html, text


def template_account_blocked(
    user_name: str,
    minutes: int,
) -> tuple[str, str, str]:
    subject = "Sua conta foi temporariamente bloqueada"
    html = _wrap(f"""
      <h1>Ola, {user_name}</h1>
      <p>Detectamos varias tentativas de login com senha incorreta na sua conta.</p>
      <p>Por seguranca, sua conta foi <strong>bloqueada temporariamente por {minutes} minutos</strong>.</p>
      <p>Se nao foi voce, considere trocar sua senha apos o desbloqueio.</p>
    """)
    text = f"Conta bloqueada por {minutes} minutos apos varias tentativas falhas de login."
    return subject, html, text


def template_password_reset_code(
    user_name: str,
    code: str,
    minutes_valid: int = 15,
) -> tuple[str, str, str]:
    subject = "Codigo para redefinir sua senha"
    html = _wrap(f"""
      <h1>Ola, {user_name}</h1>
      <p>Voce solicitou redefinicao de senha. Use o codigo abaixo:</p>
      <div class="meta" style="text-align:center;font-size:28px;letter-spacing:6px;font-weight:700;color:#1e3a8a">
        {code}
      </div>
      <p>Valido por <strong>{minutes_valid} minutos</strong>.</p>
      <p>Se nao foi voce que solicitou, ignore este email — sua senha continua segura.</p>
    """)
    text = f"Seu codigo de redefinicao: {code}\nValido por {minutes_valid} minutos."
    return subject, html, text


def template_smtp_test(admin_name: str) -> tuple[str, str, str]:
    subject = "Teste de envio - Economart"
    html = _wrap(f"""
      <h1>SMTP funcionando!</h1>
      <p>Ola, {admin_name}. Este email confirma que a configuracao SMTP esta operacional.</p>
      <p>Voce pode habilitar o envio automatico nas configuracoes do admin.</p>
    """)
    text = "Teste de SMTP enviado com sucesso."
    return subject, html, text
