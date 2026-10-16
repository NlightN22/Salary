"""Simple manually entered payment statement."""
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Spacer

from generators.chief_pdf_generator import _cell, _table, money
from services.report_io import MONTHS


def generate_manual_pdf(path, report, year, month, payments):
    style = ParagraphStyle("ManualCell", fontName="DejaVuSans", fontSize=9, leading=13)
    heading = ParagraphStyle("ManualHeading", parent=style, fontSize=15, leading=20)
    rows = [[_cell(value, style) for value in ("Название выплаты", "Сумма", "Комментарий")]]
    for payment in payments:
        rows.append([_cell(payment.title, style), _cell(money(payment.amount), style),
                     _cell(payment.comment, style)])
    rows.append([_cell("Итого к выплате", style), _cell(money(report["salary_total"]), style), ""])
    story = [
        _cell(f"Расчет: {report['employee']}", heading),
        _cell(f"{MONTHS[month].capitalize()} {year}", style), Spacer(1, 5 * mm),
        _table(rows, [65 * mm, 35 * mm, 80 * mm]),
    ]
    SimpleDocTemplate(str(path), leftMargin=15 * mm, rightMargin=15 * mm,
                      topMargin=15 * mm, bottomMargin=15 * mm).build(story)
