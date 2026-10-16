from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from services.report_naming import MONTHS
from services.rounding import round_half_up
from generators.debt_adjustments import debt_adjustment_table


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = PROJECT_ROOT / "fonts" / "DejaVuSans.ttf"
if "DejaVuSans" not in pdfmetrics.getRegisteredFontNames():  # pragma: no branch - import-time environment
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(FONT_PATH)))


def money(value):
    return f"{float(value):,.2f}".replace(",", " ")


def _cell(value, style):
    """Create a wrapping table cell and safely escape user-entered text."""
    text = "" if value is None else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _table(rows, widths=None, header_color="#ADD8E6"):
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.7, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_color)),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F9FC")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def _keep_headings_with_tables(story):
    """Prevent a section heading/description from being orphaned from its table."""
    section_started = False
    for flowable in story:
        if isinstance(flowable, Paragraph) and flowable.style.name == "Heading2":
            section_started = True
        if section_started:
            flowable.keepWithNext = True
        if isinstance(flowable, Table):
            flowable.keepWithNext = False
            section_started = False


def generate_chief_pdf(pdf_path, report, year, month):
    doc = SimpleDocTemplate(str(pdf_path), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=15 * mm, bottomMargin=15 * mm)
    styles = getSampleStyleSheet()
    for style in styles.byName.values():
        style.fontName = "DejaVuSans"
    debt_cell_style = ParagraphStyle(
        "DebtCell",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        fontSize=7.5,
        leading=9,
        splitLongWords=True,
        spaceBefore=0,
        spaceAfter=0,
    )
    additional_cell_style = ParagraphStyle(
        "AdditionalCell",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        fontSize=8,
        leading=10,
        splitLongWords=True,
        spaceBefore=0,
        spaceAfter=0,
    )
    story = [
        Paragraph(f"Расчёт руководителя B2B-направления за {MONTHS[month]} {year} года", styles["Title"]),
        Paragraph(report["employee"], styles["Heading1"]), Spacer(1, 8),
    ]
    profit, kpi = report["profit"], report["profit"]["kpi"]
    profit_rows = [
        ["Показатель", "Значение"],
        ["Показатели по сумме прибыли", ""],
        ["Сумма продаж (справочно)", money(profit["sales"])],
        ["План по сумме прибыли", money(kpi["plan"])],
        ["Факт по сумме прибыли", money(kpi["fact"])],
        ["Выполнение плана по прибыли", f'{kpi["percent"]:.2f}%'],
        ["Показатели рентабельности", ""],
        ["План по рентабельности", f'{kpi["profitability_base_percent"]:.2f}%'],
        ["Факт по рентабельности", f'{profit["profitability"]:.2f}%'],
        ["Выполнение плана по рентабельности", f'{kpi["profitability_percent"]:.2f}%'],
        ["Итоговый расчёт KPI", ""],
        ["Выполнение по прибыли × 0,6", f'{kpi["income_weighted_percent"]:.2f}%'],
        ["Выполнение по рентабельности × 0,4", f'{kpi["profitability_weighted_percent"]:.2f}%'],
        ["Итоговое выполнение KPI", f'{kpi["total_percent"]:.2f}%'],
        ["Базовый размер KPI", money(kpi["bonus_base"])],
        ["Бонус за прибыль", money(kpi["bonus"])],
    ]
    profit_table = _table(profit_rows, [105 * mm, 45 * mm])
    profit_table.setStyle(TableStyle([
        ("SPAN", (0, 1), (-1, 1)),
        ("SPAN", (0, 6), (-1, 6)),
        ("SPAN", (0, 10), (-1, 10)),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#DCE6F1")),
        ("BACKGROUND", (0, 6), (-1, 6), colors.HexColor("#E2F0D9")),
        ("BACKGROUND", (0, 10), (-1, 10), colors.HexColor("#FFF2CC")),
        ("FONTNAME", (0, 1), (-1, 1), "DejaVuSans"),
        ("FONTNAME", (0, 6), (-1, 6), "DejaVuSans"),
        ("FONTNAME", (0, 10), (-1, 10), "DejaVuSans"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2F0D9")),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.darkgreen),
    ]))
    story += [Paragraph("1. Доход", styles["Heading2"]), Paragraph(
        "Итоговый KPI складывается из выполнения плана по доходу с весом 60% и "
        "отношения текущей рентабельности к базовой рентабельности с весом 40%. "
        "Полученный процент умножается на базовый размер KPI.", styles["BodyText"]),
        Spacer(1, 4), profit_table, Spacer(1, 6)]
    cycle = report["cycle"]
    story += [Paragraph("2. Цикл сделки", styles["Heading2"]), Paragraph(
        "Показатель отражает скорость прохождения сделок по воронке продаж. Для расчёта "
        "определяется средний цикл успешно завершённых сделок («Отгрузка и доставка») и "
        "средний возраст текущих активных сделок. Чем быстрее текущие сделки проходят "
        "этапы относительно исторического цикла, тем выше бонус.", styles["BodyText"]), Spacer(1, 4), _table([
        ["Показатель", "Значение"],
        ["Сделок в расчете плана", str(cycle["plan_count"])],
        ["Сделок в расчете факта", str(cycle["fact_count"])],
        ["Цикл сделки, план", f'{cycle["plan"]:.2f} дн.'],
        ["Цикл сделки, факт", f'{cycle["fact"]:.2f} дн.'],
        ["Соотношение", f'{cycle["ratio"] * 100:.2f}%'],
        ["Базовый размер бонуса", money(cycle["bonus_base"])],
        ["Размер бонуса", money(cycle["bonus"])],
    ], [95 * mm, 55 * mm], "#FFF2CC"), Spacer(1, 6)]
    zic = report["zic"]
    story += [Paragraph("3. ZIC", styles["Heading2"]), _table([
        ["Показатель", "План", "Факт", "% выполнения", "Стоимость KPI", "Бонус"],
        [zic["brand"], money(zic["plan"]), money(zic["fact"]), f'{zic["percent"]:.2f}%',
         money(zic["bonus_base"]), money(zic["bonus"])],
    ], header_color="#FFE699"), Spacer(1, 6)]
    other = report["other"]
    other_rows = [["Показатель", "% выполнения", "Вес", "Итог %"]]
    other_rows += [[item["brand"], f'{item["percent"]:.2f}%', f'{item["weight"]:.2f}%',
                    f'{item["weighted_percent"]:.2f}%'] for item in other["items"]]
    other_rows += [["ИТОГО", "", "", f'{other["percent"]:.2f}%'],
                   ["К расчёту", "", "", f'{other["calculation_percent"]:.2f}%'],
                   ["Бонус", "", money(other["bonus_base"]), money(other["bonus"])]]
    story += [Paragraph("4. Спец продукты", styles["Heading2"]), Paragraph(
        "Итоговый показатель определяется как сумма выполнения KPI с учётом установленных весов. "
        "Если выполнение превышает 120%, к расчёту принимается 120%. "
        "Если выполнение ниже 50%, результат умножается на коэффициент 0,8. В остальных "
        "случаях используется фактическое выполнение. Полученный коэффициент умножается "
        "на базовый размер бонуса.",
        styles["BodyText"]), Spacer(1, 4), _table(other_rows, header_color="#C6E0B4"), Spacer(1, 6)]
    debt = report["debt"]
    story += [Paragraph("5. Просроченная дебиторская задолженность", styles["Heading2"]),
              Paragraph("Общая ПДЗ определяется на конец отчётного месяца. Ответственность "
                        "рассчитывается аналогично менеджерам и вычитается из премии.", styles["BodyText"]),
              Spacer(1, 4), _table([["Показатель", "Значение"],
              ["Общая ПДЗ", money(debt["total"])],
              ["Ответственность за ПДЗ (1% от суммы)", "-" + money(debt["responsibility"])]],
              [95 * mm, 55 * mm], "#FCE4D6"), Spacer(1, 4)]
    story.extend(debt_adjustment_table(debt))
    debt_threshold = f"{float(debt['threshold']):,.0f}".replace(",", " ")
    story += [Paragraph(
        f"В таблице ниже отдельно отмечены клиенты с просроченной "
        f"задолженностью {debt_threshold} рублей и более.",
        styles["BodyText"],
    ), Spacer(1, 4)]
    debt_rows = [[
        _cell("Контрагент", debt_cell_style),
        _cell("Сумма задолженности", debt_cell_style),
        _cell("Комментарий", debt_cell_style),
    ]]
    debt_rows += [[
        _cell(item["contractor"] or "В исходном debt.xlsx нет колонки «Контрагент»", debt_cell_style),
        _cell(money(item["overdue"]), debt_cell_style),
        _cell(item["comment"], debt_cell_style),
    ] for item in debt["large_items"]]
    if len(debt_rows) == 1:
        debt_rows.append([_cell("Случаи не найдены", debt_cell_style), "", ""])
    story += [_table(debt_rows, [65 * mm, 35 * mm, 80 * mm], "#F4B183"), Spacer(1, 6)]
    lukoil = report["lukoil"]
    lukoil_rows = [["Менеджер", "Бонус менеджера"]]
    if lukoil.get("calculation_enabled", True):
        lukoil_rows += [[item["employee"], money(item["manager_bonus"])] for item in lukoil["manager_items"]]
        lukoil_rows += [
            ["Сумма бонусов менеджеров", money(lukoil["manager_bonus_total"])],
            [f'Коэффициент руководителя ({lukoil["coefficient"] * 100:.0f}%)', money(lukoil["bonus"])],
        ]
        lukoil_description = (
            "Учитываются бонусы менеджеров по оплаченному товару Лукойл. Бонус "
            "руководителя равен сумме бонусов таких менеджеров, умноженной на 0,25."
        )
    else:
        lukoil_rows.append(["", ""])
        lukoil_description = "Расчёт будет добавлен после подключения отдельного отчёта."
    story += [Paragraph("6. Лукойл", styles["Heading2"]), Paragraph(
              lukoil_description,
              styles["BodyText"]), Spacer(1, 4), _table(lukoil_rows, [105 * mm, 45 * mm], "#BDD7EE")]
    key_clients = report["key_clients_profit"]
    key_client_rows = [["Клиент", "Размер прибыли", "Размер бонуса"]]
    key_client_rows += [[
        item["client"],
        "" if item["profit"] is None else money(item["profit"]),
        "" if item["bonus"] is None else money(item["bonus"]),
    ] for item in key_clients["items"]]
    story += [Paragraph("7. Чистая прибыль по ключевым клиентам", styles["Heading2"]),
              Paragraph("Бонус составляет 10% от прибыли по основным крупным клиентам "
                        "(добывающие компании, крупные производители).", styles["BodyText"]),
              Spacer(1, 4), _table(key_client_rows, [75 * mm, 40 * mm, 40 * mm], "#D9EAD3")]
    timesheet = report["timesheet"]
    story += [Paragraph("8. Оклад", styles["Heading2"]), _table([
        ["Отработано часов", "Оклад"], [f'{timesheet["hours"]:.2f}', money(timesheet["salary"])],
    ], header_color="#D9E1F2"), Spacer(1, 6)]
    additional_payments = report["additional_payments"]
    additional_total = round_half_up(sum(
        float(item.get("amount") or 0)
        for item in additional_payments.get("items", [])
    ))
    additional_rows = [["Описание", "Сумма"]]
    additional_rows += [[
        _cell(item["description"], additional_cell_style),
        "" if item["amount"] is None else money(item["amount"]),
    ] for item in additional_payments["items"]]
    story += [Paragraph("9. Дополнительные выплаты", styles["Heading2"]),
              _table(additional_rows, [105 * mm, 45 * mm], "#E4DFEC"), Spacer(1, 6)]
    total_bonus = round_half_up(
        kpi["bonus"] + cycle["bonus"] + zic["bonus"] + other["bonus"]
        + lukoil["bonus"] + key_clients["bonus"] + additional_total
        - debt["responsibility"]
    )
    salary_total = round_half_up(total_bonus + timesheet["salary"])
    total_table = _table([
        ["Показатель", "Сумма"], ["Бонус за прибыль", money(kpi["bonus"])],
        ["Бонус за цикл сделки", money(cycle["bonus"])], ["Бонус ZIC", money(zic["bonus"])],
        ["Бонус за спец продукты", money(other["bonus"])], ["Лукойл", money(lukoil["bonus"])],
        ["Чистая прибыль по ключевым клиентам", money(key_clients["bonus"])],
        ["Дополнительные выплаты", money(additional_total)],
        ["Ответственность за ПДЗ", "-" + money(debt["responsibility"])],
        ["ИТОГО, премия", money(total_bonus)],
        ["Оклад", money(timesheet["salary"])], ["Размер заработной платы", money(salary_total)],
    ], [100 * mm, 50 * mm], "#A9D18E")
    total_table.setStyle(TableStyle([
        ("BACKGROUND", (0, -3), (-1, -3), colors.Color(1, 0.9, 0.9)),
        ("TEXTCOLOR", (0, -3), (-1, -3), colors.red),
        ("BACKGROUND", (0, -1), (-1, -1), colors.Color(0.85, 1, 0.85)),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.darkgreen),
    ]))
    story += [Paragraph("10. Итоговый расчёт", styles["Heading2"]), total_table]
    _keep_headings_with_tables(story)
    doc.build(story)
