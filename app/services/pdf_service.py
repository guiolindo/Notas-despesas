import hashlib
import hmac
import io
import logging
import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

_logger = logging.getLogger(__name__)

BR_TZ = ZoneInfo("America/Sao_Paulo")

import qrcode
from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.models import ApprovalAction, Invoice
from app.services.drive_service import drive_service


BRAND_BLUE = colors.HexColor("#1B4F8A")
BRAND_ORANGE = colors.HexColor("#F47920")
LIGHT_GREEN = colors.HexColor("#DCFCE7")
LIGHT_GRAY = colors.HexColor("#F5F5F5")


def _invoice_hmac_key() -> bytes:
    """Chave dedicada pro codigo de conferencia do comprovante.

    SEC-02 (auditoria set/2026): antes era SHA-256 puro sobre 4 campos
    publicos da nota — qualquer pessoa que visse o PDF forjava a
    "assinatura". Agora e HMAC. Chave preferencial: INVOICE_HMAC_KEY.
    Fallback: SECRET_KEY (evita quebrar deploys existentes; ainda melhor
    que a versao anterior porque o segredo nao aparece no PDF).
    """
    from app.config import settings
    key = os.getenv("INVOICE_HMAC_KEY") or settings.SECRET_KEY
    if isinstance(key, str):
        key = key.encode("utf-8")
    return key


def invoice_hash(invoice: Invoice) -> str:
    """Codigo curto de conferencia impresso no comprovante.

    NAO e uma assinatura digital no sentido criptografico (nao ha PKI).
    E um HMAC-SHA256 truncado que so quem detem a chave consegue
    reproduzir — o suficiente pra rejeitar comprovantes forjados por
    quem ve apenas o PDF. A verdadeira verificacao de autenticidade
    acontece server-side quando o QR code aponta para /verify/{id}.
    """
    raw = f"{invoice.id}:{invoice.invoice_number}:{invoice.amount}:{invoice.created_at}".encode("utf-8")
    digest = hmac.new(_invoice_hmac_key(), raw, hashlib.sha256).hexdigest()
    return digest[:16].upper()


def _format_date(value) -> str:
    return value.strftime("%d/%m/%Y") if value else "-"


def _format_datetime(value) -> str:
    """Formata datetime no fuso de Brasilia (-3) para impressao no PDF."""
    if not value:
        return "-"
    from datetime import timezone, timedelta
    # Se naive, assume que esta em UTC (e como _now() grava). Converte pra -3.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    br_tz = timezone(timedelta(hours=-3))
    return value.astimezone(br_tz).strftime("%d/%m/%Y %H:%M")


def _format_currency(value) -> str:
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _history_entry(invoice: Invoice, action: ApprovalAction):
    for entry in invoice.approval_history:
        if entry.action == action:
            return entry
    return None


def _qr_image(url: str) -> Image:
    qr = qrcode.QRCode(box_size=4, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return Image(buffer, width=80, height=80)


def _approval_row(invoice: Invoice, action: ApprovalAction, label: str, status_text: str, show_email: bool = False):
    """show_email=True inclui email do responsavel (etapas de aprovacao)."""
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

    entry = _history_entry(invoice, action)
    if entry and entry.user:
        if show_email and entry.user.email:
            # Nome em negrito + email pequeno embaixo
            cell_styles = getSampleStyleSheet()
            small = ParagraphStyle(
                name=f"_small_{label}", parent=cell_styles["Normal"],
                fontSize=7, leading=9, textColor=colors.HexColor("#4B5563"),
            )
            responsavel = Paragraph(
                f"<b>{entry.user.name}</b><br/><font size=7>{entry.user.email}</font>",
                cell_styles["Normal"],
            )
        else:
            responsavel = entry.user.name
    else:
        responsavel = "-"
    return [
        label,
        responsavel,
        _format_datetime(entry.timestamp if entry else None),
        status_text if entry else "Pendente",
    ]


def _build_cover_pdf(invoice: Invoice, base_url: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="BrandTitle",
            parent=styles["Title"],
            textColor=BRAND_BLUE,
            fontName="Helvetica-Bold",
            fontSize=18,
            alignment=0,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="DocTitle",
            parent=styles["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            alignment=1,
            spaceBefore=8,
            spaceAfter=14,
        )
    )
    styles.add(ParagraphStyle(name="Small", parent=styles["Normal"], fontSize=8, leading=10))

    story = [
        Paragraph("Economart Atacadista", styles["BrandTitle"]),
        Table([[""]], colWidths=[174 * mm], rowHeights=[2]),
        Paragraph("COMPROVANTE DE APROVACAO DE NOTA FISCAL", styles["DocTitle"]),
    ]
    story[1].setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BRAND_ORANGE)]))

    dept_obj = invoice.created_by.department_obj if invoice.created_by else None
    sector_name = dept_obj.name if dept_obj else "-"
    data = [
        ["Numero da Nota", invoice.invoice_number],
        ["Setor", sector_name],
        ["Data de Emissao", _format_date(invoice.issue_date)],
        ["Data de Vencimento", _format_date(invoice.due_date)],
        ["Valor", _format_currency(invoice.amount)],
        ["Descricao", Paragraph(invoice.description or "-", styles["Normal"])],
        ["Dados Bancarios", Paragraph(invoice.bank_details or "Nao informado", styles["Normal"])],
    ]
    data_table = Table(data, colWidths=[45 * mm, 125 * mm])
    data_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), LIGHT_GRAY),
                ("TEXTCOLOR", (0, 0), (0, -1), BRAND_BLUE),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([data_table, Spacer(1, 12)])

    paid_row = []
    if invoice.status.value == "PAGO":
        paid_row = [["Lancamento", invoice.finance.name if invoice.finance else "-", _format_datetime(invoice.paid_at), "Lancada"]]
    approval_data = [
        ["Etapa", "Responsavel", "Data/Hora", "Status"],
        _approval_row(invoice, ApprovalAction.CREATED, "Criacao", "Criado"),
        _approval_row(invoice, ApprovalAction.SUBMITTED, "Envio", "Enviado"),
        _approval_row(invoice, ApprovalAction.APPROVED_MANAGER, "Aprovacao Gestor", "Aprovado", show_email=True),
        _approval_row(invoice, ApprovalAction.APPROVED_DIRECTOR, "Aprovacao Diretor", "Aprovado", show_email=True),
        *paid_row,
    ]
    approval_table = Table(approval_data, colWidths=[45 * mm, 48 * mm, 42 * mm, 35 * mm])
    approval_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), BRAND_BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("BACKGROUND", (0, 1), (-1, -1), LIGHT_GREEN),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E5E7EB")),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    story.extend([Paragraph("Trilha de Aprovacao", styles["Heading3"]), approval_table, Spacer(1, 14)])

    verify_url = f"{base_url.rstrip('/')}/verify/{invoice.id}"
    signature = invoice_hash(invoice)
    generated_at = datetime.now(BR_TZ).strftime("%d/%m/%Y %H:%M")
    footer_table = Table(
        [
            [
                Paragraph(
                    f"<b>Assinatura Digital:</b> {signature}<br/><b>Gerado em:</b> {generated_at}<br/>Este documento possui validade mediante verificacao do QR Code.",
                    styles["Small"],
                ),
                [_qr_image(verify_url), Paragraph("Escaneie para verificar autenticidade", styles["Small"])],
            ]
        ],
        colWidths=[125 * mm, 45 * mm],
    )
    footer_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM")]))
    story.append(footer_table)

    doc.build(story)
    return buffer.getvalue()


# BE-08 (auditoria set/2026): teto de paginas do documento final.
# 5 anexos x ate 500 paginas cada = 2500 e mais que suficiente pra
# nota fiscal real. Evita ataque com PDF de milhoes de paginas via
# object reference explosion, protegendo memoria/cpu do worker.
_MAX_MERGED_PAGES = 2500


def generate_print_pdf(invoice: Invoice, base_url: str) -> bytes:
    """Gera comprovante: capa + TODOS os anexos da nota concatenados.

    Anexos sao baixados/descriptografados em ordem de upload e mesclados
    em um unico PDF de comprovante. Se algum anexo falhar (R2 fora,
    chave invalida), apenas pula esse anexo — comprovante segue valido
    com os outros.

    BE-08: para em _MAX_MERGED_PAGES paginas. Anexos alem do limite
    sao ignorados com log warning.
    """
    cover_pdf = _build_cover_pdf(invoice, base_url)
    attachments = invoice.attachments or []
    if not attachments:
        return cover_pdf

    writer = PdfWriter()
    total_pages = 0
    # Capa primeiro
    for page in PdfReader(io.BytesIO(cover_pdf)).pages:
        writer.add_page(page)
        total_pages += 1

    # Cada anexo, em ordem
    for att in attachments:
        if not att.drive_file_id or not att.encryption_key_enc:
            continue
        if total_pages >= _MAX_MERGED_PAGES:
            _logger.warning(
                "[pdf] limite de %d paginas atingido; anexos restantes da nota %s ignorados",
                _MAX_MERGED_PAGES, invoice.id,
            )
            break
        try:
            att_bytes = drive_service.download_and_decrypt(
                att.drive_file_id, att.encryption_key_enc,
            )
            for page in PdfReader(io.BytesIO(att_bytes)).pages:
                if total_pages >= _MAX_MERGED_PAGES:
                    break
                writer.add_page(page)
                total_pages += 1
        except Exception as exc:  # noqa: BLE001
            # BE-01 (auditoria set/2026): antes era silencioso — anexo
            # que falhava sumia do comprovante oficial sem qualquer
            # sinal, e ninguem sabia que o PDF entregue estava
            # incompleto. Agora loga com contexto suficiente pra
            # diagnostico. A concatenacao segue (nao quebrar comprovante
            # inteiro por 1 anexo ruim), mas o log fica.
            _logger.warning(
                "[pdf] falha ao mesclar anexo id=%s da nota %s: %s",
                att.id, invoice.id, exc,
            )
            continue

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
