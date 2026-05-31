"""Servico de envio de emails — configuracao SOMENTE via env (.env).

Decisao de seguranca: o admin do app NAO pode mais editar SMTP pela UI.
Razao: admin malicioso poderia trocar o provedor por um servidor proprio
e interceptar codigos de reset de senha de outros admins/diretores. Agora
o provedor SMTP/Resend vive em variaveis de ambiente — controlado por
quem opera a infra (Railway), nao por quem tem login no app.

Envios sao defensivos: erro de SMTP NUNCA quebra o fluxo principal —
apenas loga e segue, evitando que email caido impeca aprovacao de notas.
"""
from __future__ import annotations

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

from sqlalchemy.orm import Session

from app.config import settings


logger = logging.getLogger(__name__)


def _email_provider() -> str:
    """Retorna provider efetivo: SMTP, RESEND ou DISABLED."""
    p = (settings.EMAIL_PROVIDER or "SMTP").upper()
    if p == "DISABLED":
        return "DISABLED"
    if p == "RESEND" and settings.RESEND_API_KEY:
        return "RESEND"
    if p == "SMTP" and settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD:
        return "SMTP"
    return "DISABLED"  # falta credencial -> tratado como desabilitado


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
    text_part = text or "Esta mensagem requer um cliente que renderize HTML."
    msg.attach(MIMEText(text_part, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def send_email(
    db: Optional[Session],          # parametro mantido por compat com chamadas antigas
    to_email: str,
    subject: str,
    html: str,
    text: Optional[str] = None,
) -> bool:
    """Envia email via provider configurado em .env. Best-effort."""
    provider = _email_provider()
    if provider == "DISABLED":
        logger.info(f"[email] desabilitado — pulando envio para {to_email}")
        return False
    if provider == "RESEND":
        return _send_via_resend(to_email, subject, html, text)
    return _send_via_smtp(to_email, subject, html, text)


def _send_via_smtp(to_email, subject, html, text):
    from_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    from_name = settings.SMTP_FROM_NAME or "Economart"
    msg = _build_message(from_email, from_name, to_email, subject, html, text)
    try:
        if settings.SMTP_USE_TLS:
            ctx = ssl.create_default_context()
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.ehlo()
                server.starttls(context=ctx)
                server.ehlo()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
        logger.info(f"[email-smtp] enviado para {to_email}: {subject}")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[email-smtp] falha para {to_email}: {exc}")
        return False


def _send_via_resend(to_email, subject, html, text):
    from_email = settings.SMTP_FROM_EMAIL or "onboarding@resend.dev"
    from_name = settings.SMTP_FROM_NAME or "Economart"
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
            "Authorization": f"Bearer {settings.RESEND_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Economart-Notas/1.0 (+https://economart.com.br)",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
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
        try:
            send_email(None, to_email, subject, html, text)
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


