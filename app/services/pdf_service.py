import hashlib
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

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


def invoice_hash(invoice: Invoice) -> str:
    raw = f"{invoice.id}:{invoice.invoice_number}:{invoice.amount}:{invoice.created_at}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16].upper()


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

    data = [
        ["Numero da Nota", invoice.invoice_number],
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
        paid_row = [["Lancamento", invoice.finance.name if invoice.finance else "-", _format_datetime(invoice.paid_at), "Pago"]]
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


def generate_print_pdf(invoice: Invoice, base_url: str) -> bytes:
    cover_pdf = _build_cover_pdf(invoice, base_url)
    if not invoice.drive_file_id or not invoice.encryption_key_enc:
        return cover_pdf

    original_pdf = drive_service.download_and_decrypt(
        invoice.drive_file_id,
        invoice.encryption_key_enc,
    )
    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(cover_pdf)).pages:
        writer.add_page(page)
    for page in PdfReader(io.BytesIO(original_pdf)).pages:
        writer.add_page(page)

    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
