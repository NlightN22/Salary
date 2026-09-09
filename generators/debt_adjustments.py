from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle


def debt_adjustment_table(debt):
    """Render debt changes separately from bonuses and additional payments."""
    if not debt.get("corrections"):
        return []
    style = ParagraphStyle("DebtCorrectionCell", fontName="DejaVuSans",
                           fontSize=8, leading=11, splitLongWords=True)

    def cell(value):
        return Paragraph(escape(str(value)).replace("\n", "<br/>"), style)

    def money(value):
        return f"{float(value):,.2f}".replace(",", " ")

    rows = [[cell("Запись / комментарий"), cell("Сумма, руб.")],
            [cell("ПДЗ по исходному отчету"), cell(money(debt["original_total"]))]]
    rows.extend([cell(item["comment"]), cell(money(item["amount"]))] for item in debt["corrections"])
    rows.extend([
        [cell("Итого корректировки ПДЗ"), cell(money(debt["adjustment_total"]))],
        [cell("ПДЗ с учетом корректировок"), cell(money(debt["total"]))],
    ])
    table = Table(rows, colWidths=[135 * mm, 45 * mm], repeatRows=1)
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), .7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F4B183")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF2CC")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    heading = Paragraph("Корректировки суммы ПДЗ", style)
    heading.keepWithNext = True
    return [Spacer(1, 8), heading, table, Spacer(1, 6)]
