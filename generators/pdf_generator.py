from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.styles import ParagraphStyle

from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

from services.rounding import round_half_up

# ==================================================
# Регистрация шрифта
# ==================================================

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FONT_PATH = PROJECT_ROOT / "fonts" / "DejaVuSans.ttf"

pdfmetrics.registerFont(
    TTFont(
        "DejaVuSans",
        str(FONT_PATH)
    )
)


# ==================================================
# Форматирование денег
# ==================================================

from generators.debt_adjustments import debt_adjustment_table


def money(value):

    try:
        return f"{float(value):,.2f}".replace(",", " ")
    except Exception:
        return "0.00"


def _cell(value, style):
    text = "" if value is None else str(value)
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


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


# ==================================================
# Генерация PDF
# ==================================================

def generate_pdf(
    pdf_path,
    employee,
    profit_data,
    brand_data,
    debt_data,
    cycle_data,
    communications,
    timesheet_data,
    additional_payments,
    year,
    month,

):
    MONTHS = {
        1: "январь",
        2: "февраль",
        3: "март",
        4: "апрель",
        5: "май",
        6: "июнь",
        7: "июль",
        8: "август",
        9: "сентябрь",
        10: "октябрь",
        11: "ноябрь",
        12: "декабрь",
    }

    pdf_path = Path(pdf_path)

    pdf_path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    doc = SimpleDocTemplate(
        str(pdf_path),
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()

    justified_style = ParagraphStyle(
        "Justified",
        parent=styles["BodyText"],
        fontName="DejaVuSans",
        alignment=TA_JUSTIFY,
    )

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
        fontSize=9,
        leading=11,
        splitLongWords=True,
        spaceBefore=0,
        spaceAfter=0,
    )

    story = []

    # ==================================================
    # Заголовок
    # ==================================================

    story.append(
        Paragraph(
            f"Расчёт сотрудника b2b-направления за "
            f"{MONTHS[month]} {year} года",
            styles["Title"]
        )
    )

    story.append(
        Paragraph(
            employee,
            styles["Title"]
        )
    )

    story.append(
        Spacer(1, 10)
    )

    # ==================================================
    # Доход
    # ==================================================

    story.append(
        Paragraph(
            "1.Доход",
            styles["Heading2"]
        )
    )

    profit_table = Table(
        [
            ["Показатель", "Значение"],

            [
                "Сумма продаж",
                money(profit_data["sales"]),
            ],

            [
                "Доход текущий",
                money(profit_data["income"]),
            ],

            [
                "Рентабельность текущая",
                f'{profit_data["profitability"]:.2f}%',
            ],

            [
                "Бонус от дохода 5%",
                money(profit_data["bonus"]),
            ],
        ],
        colWidths=[90 * mm, 50 * mm],
    )

    profit_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
            ]
        )
    )

    story.append(profit_table)

    story.append(
        Spacer(1, 10)
    )

    # ==================================================
    # KPI ZIC
    # ==================================================

    story.append(
        Paragraph(
            "2.KPI ZIC",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            "Показатель работы по KPI ZIC. Базовый размер бонуса 40.000 руб. зависит от % выполнения. ",
            justified_style
        )
    )

    story.append(
        Spacer(1, 10)
    )

    zic_rows = [
        [
            "Показатель",
            "План",
            "Факт",
            "% выполнения",
            "Размер бонуса",
        ]
    ]

    for item in brand_data["zic"]:
        zic_rows.append(
            [
                item["brand"],
                money(item["plan"]),
                money(item["fact"]),
                f"{item['percent']:.2f}",
                money(item["bonus"]),
            ]
        )

    zic_table = Table(zic_rows)

    zic_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgoldenrodyellow),
            ]
        )
    )

    story.append(zic_table)

    story.append(
        Spacer(1, 10)
    )

    # ==================================================
    # Лукойл
    # ==================================================

    story.append(
        Paragraph(
            "3. Лукойл",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            "Размер бонусирования при продаже "
            "от 0 до 499 кг — 0 рублей за кг., "
            "от 500 до 1999 кг — 5 рублей за кг., "
            "от 2000 до 4999 кг — 8 рублей за кг., "
            "от 5000 кг — 10 рублей за кг.",
            justified_style
        )
    )

    story.append(
        Spacer(1, 10)
    )

    if brand_data["lukoil"]:
        lukoil_table = Table(
            [
                ["Показатель", "Значение"],

                [
                    "Объём продаж, кг",
                    money(
                        brand_data["lukoil"]["kg"]
                    ),
                ],

                [
                    "Ставка, руб./кг",
                    money(
                        brand_data["lukoil"]["rate"]
                    ),
                ],

                [
                    "Бонус",
                    money(
                        brand_data["lukoil"]["bonus"]
                    ),
                ],
            ],
            colWidths=[90 * mm, 50 * mm],
        )

        lukoil_table.setStyle(
            TableStyle(
                [
                    ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                    ("GRID", (0, 0), (-1, -1), 1, colors.black),
                    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(1, 0.9, 0.9)),
                ]
            )
        )

        story.append(lukoil_table)

    story.append(
        Spacer(1, 10)
    )

    # ==================================================
    # Другие KPI
    # ==================================================

    story.append(
        Paragraph(
            "4.Другие KPI",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            "Итоговый показатель «Другие KPI» определяется как сумма "
            "результатов выполнения отдельных KPI с учётом их весов в общей "
            "структуре оценки. Для расчёта бонуса применяется ограничение: "
            "максимальное учитываемое выполнение — 120%, минимальное — 10%. "
            "Базовый размер бонуса — 30 000 руб.",
            justified_style
        )
    )

    story.append(
        Spacer(1, 10)
    )


    other_rows = [
        [
            "Показатель",
            "План",
            "Факт",
            "% выполнения",
            "Вес KPI",
            "Итог %",
        ]
    ]

    other_total_percent = 0

    for item in brand_data["other"]:
        other_total_percent += item["weighted_percent"]

        other_rows.append(
            [
                item["brand"],
                money(item["plan"]),
                money(item["fact"]),
                f"{item['percent']:.2f}%",
                f"{item['weight']:.2f}%",
                f"{item['weighted_percent']:.2f}%",
            ]
        )

    other_rows.append(
        [
            "",
            "",
            "",
            "",
            "ИТОГО",
            f"{other_total_percent:.2f}%",
        ]
    )

    other_rows.append(
        [
            "",
            "",
            "",
            "",
            "Бонус",
            money(
                brand_data["other_bonus_total"]
            ),
        ]
    )

    other_table = Table(
        other_rows,
        colWidths=[
            45 * mm,
            22 * mm,
            22 * mm,
            30 * mm,
            25 * mm,
            25 * mm,
        ]
    )

    other_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgreen),
            ]
        )
    )

    story.append(other_table)

    story.append(
        Spacer(1, 50)
    )

    # ==================================================
    # Дебиторская задолженность
    # ==================================================

    story.append(
        Paragraph(
            "5.Дебиторская задолженность",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            "Общая сумма просроченной дебиторской задолженности определяется по состоянию на 23:59:59 последнего дня отчетного месяца.",
            justified_style
        )
    )

    story.append(
        Spacer(1, 10)
    )

    debt_table = Table(
        [
            ["Показатель", "Значение"],

            [
                "Общая просроченная задолженность",
                money(
                    debt_data["total"]
                ),
            ],

            [
                "Ответственность за ПДЗ (1% от суммы)",
                f"-{money(debt_data['responsibility'])}",
            ],

            [
                "Отношение ПДЗ к обороту (справочно)",
                f"{debt_data['ratio']:.2f}%",
            ],
        ],
        colWidths=[90 * mm, 50 * mm],
    )

    debt_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.beige),
            ]
        )
    )

    story.append(debt_table)
    story.extend(debt_adjustment_table(debt_data))

    debt_threshold = f"{float(debt_data['threshold']):,.0f}".replace(",", " ")
    story.append(Spacer(1, 4))
    story.append(Paragraph(
        f"В таблице ниже отдельно отмечены клиенты с просроченной "
        f"задолженностью {debt_threshold} рублей и более.",
        justified_style,
    ))

    debt_rows = [[
        _cell("Контрагент", debt_cell_style),
        _cell("Сумма задолженности", debt_cell_style),
        _cell("Комментарий", debt_cell_style),
    ]]
    debt_rows += [[
        _cell(item["contractor"] or "В исходном debt.xlsx нет колонки «Контрагент»", debt_cell_style),
        _cell(money(item["overdue"]), debt_cell_style),
        _cell(item["comment"], debt_cell_style),
    ] for item in debt_data["large_items"]]
    if len(debt_rows) == 1:
        debt_rows.append([_cell("Случаи не найдены", debt_cell_style), "", ""])

    debt_details_table = Table(
        debt_rows,
        colWidths=[65 * mm, 35 * mm, 80 * mm],
        repeatRows=1,
    )
    debt_details_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.beige),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(Spacer(1, 4))
    story.append(debt_details_table)

    story.append(
        Spacer(1, 5)
    )

    # ==================================================
    # Цикл сделки
    # ==================================================

    story.append(
        Paragraph(
            "6. Цикл сделки",
            styles["Heading2"]
        )
    )

    story.append(
        Paragraph(
            "Показатель отражает скорость прохождения сделок по воронке продаж. "
            "Для расчёта определяется средний цикл успешно завершённых сделок («Отгрузка и доставка») и средний возраст текущих активных сделок. "
            "Размер бонуса зависит от соотношения этих показателей: чем быстрее текущие сделки проходят этапы воронки относительно исторического цикла продаж, тем выше бонус.",
            justified_style
        )
    )

    story.append(
        Spacer(1, 5)
    )

    cycle_table = Table(
        [
            ["Показатель", "Значение"],

            [
                "Сделок в расчете плана",
                str(
                    cycle_data["plan_count"]
                )
            ],

            [
                "Сделок в расчете факта",
                str(
                    cycle_data["fact_count"]
                )
            ],

            [
                "Цикл сделки, план",
                f"{cycle_data['plan']:.2f} дн."
            ],

            [
                "Цикл сделки, факт",
                f"{cycle_data['fact']:.2f} дн."
            ],

            [
                "Соотношение",
                f"{cycle_data['ratio'] * 100:.2f}%"
            ],

            [
                "Размер бонуса",
                money(
                    cycle_data["bonus"]
                )
            ],

        ],
        colWidths=[90 * mm, 50 * mm],
    )

    cycle_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightyellow),
            ]
        )
    )

    story.append(cycle_table)

    story.append(
        Spacer(1, 5)
    )




    # ==================================================
    # Коммуникации за месяц
    # ==================================================

    story.append(
        Paragraph(
            "7.Коммуникации за месяц",
            styles["Heading2"]
        )
    )

    comm_rows = [
        [
            "Тип коммуникации",
            "Всего",
            "Успешно",
            "Неудачно",
        ]
    ]

    for name, data in communications.items():
        comm_rows.append(
            [
                name.capitalize(),
                str(data["total"]),
                str(data["success"]),
                str(data["failed"]),
            ]
        )

    comm_table = Table(
        comm_rows,
        colWidths=[
            70 * mm,
            25 * mm,
            25 * mm,
            25 * mm,
        ]
    )

    comm_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
            ]
        )
    )

    story.append(comm_table)

    story.append(
        Spacer(1, 5)
    )


    # ==================================================
    # Дополнительные выплаты
    # ==================================================

    additional_total = round_half_up(sum(
        float(item.get("amount") or 0)
        for item in additional_payments.get("items", [])
    ))

    story.append(Paragraph("8. Дополнительные выплаты", styles["Heading2"]))
    additional_rows = [["Описание", "Сумма"]]
    for item in additional_payments["items"]:
        additional_rows.append([
            _cell(item["description"], additional_cell_style),
            "" if item["amount"] is None else money(item["amount"]),
        ])
    additional_table = Table(additional_rows, colWidths=[90 * mm, 50 * mm])
    additional_table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
    ]))
    story.append(additional_table)
    story.append(Spacer(1, 5))

    # ==================================================
    # Итог
    # ==================================================

    total_bonus = round_half_up(
            profit_data["bonus"]
            + brand_data["zic_bonus_total"]
            + brand_data["lukoil_bonus"]
            + brand_data["other_bonus_total"]
            + cycle_data["bonus"]
            + additional_total
            - debt_data["responsibility"]
    )

    salary_total = round_half_up(
            total_bonus
            + timesheet_data["salary"]
    )

    total_table = Table(
        [
            ["Показатель", "Сумма"],

            [
                "Бонус от дохода 5%",
                money(
                    profit_data["bonus"]
                ),
            ],

            [
                "Бонус KPI ZIC",
                money(
                    brand_data["zic_bonus_total"]
                ),
            ],

            [
                "Бонус Лукойл",
                money(
                    brand_data["lukoil_bonus"]
                ),
            ],

            [
                "Бонус за другие KPI",
                money(
                    brand_data["other_bonus_total"]
                ),
            ],

            [
                "Ответственность за ПДЗ",
                f"-{money(debt_data['responsibility'])}",
            ],

            [
                "Бонус за цикл сделки",
                money(
                    cycle_data["bonus"]
                ),
            ],

            [
                "Дополнительные выплаты",
                money(additional_total),
            ],

            [
                "ИТОГО, премия за месяц к выплате",
                money(total_bonus),
            ],

            [
                "Отработано часов",
                f"{timesheet_data['hours']:.2f}",
            ],

            [
                "Оклад",
                money(
                    timesheet_data["salary"]
                ),
            ],

            [
                "Размер заработной платы",
                money(
                    total_bonus
                    + timesheet_data["salary"]
                ),
            ],
        ],
        colWidths=[90 * mm, 50 * mm],
    )

    total_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), "DejaVuSans"),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),

                # ИТОГО
                ("BACKGROUND", (0, -4), (-1, -4), colors.Color(1, 0.9, 0.9)),
                ("TEXTCOLOR", (0, -4), (-1, -4), colors.Color(1, 0, 0)),

                # Оклад
                # ("BACKGROUND", (0, -2), (-1, -2), colors.lightyellow),

                # Размер заработной платы
                ("BACKGROUND", (0, -1), (-1, -1),
                 colors.Color(0.85, 1, 0.85)),

                ("TEXTCOLOR", (0, -1), (-1, -1),
                 colors.darkgreen),

                # ("FONTSIZE", (0, -1), (-1, -1), 12),
            ]
        )
    )

    story.append(
        Paragraph(
            "9. Итоговый расчёт",
            styles["Heading2"]
        )
    )

    story.append(total_table)

    _keep_headings_with_tables(story)
    doc.build(story)
