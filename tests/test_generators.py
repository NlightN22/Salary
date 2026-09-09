from pathlib import Path

from generators.chief_pdf_generator import generate_chief_pdf
from generators.docx_generator import generate_docx, money as docx_money
from generators.pdf_generator import generate_pdf, money as pdf_money


def manager_report():
    return {
        "employee": "Тестов Тест Тестович",
        "profit": {"sales": 100000, "income": 20000, "profitability": 20, "bonus": 1000},
        "brand": {
            "zic": [{"brand": "ZIC", "plan": 100, "fact": 80, "percent": 80, "bonus": 800}],
            "lukoil": {"kg": 2000, "rate": 8, "bonus": 16000},
            "other": [{"brand": "VEGA", "plan": 10, "fact": 8, "percent": 80, "weight": 50, "weighted_percent": 40}],
            "zic_bonus_total": 800, "lukoil_bonus": 16000, "other_bonus_total": 500,
        },
        "debt": {
            "total": 150000, "responsibility": 1500, "ratio": 1.5, "threshold": 100000,
            "large_items": [{"contractor": "Клиент <А>", "overdue": 150000, "comment": "Длинный\nкомментарий"}],
        },
        "cycle": {"plan": 20, "fact": 25, "ratio": .8, "bonus": 1000, "plan_count": 2, "fact_count": 3},
        "communications": {
            "звонок": {"total": 5, "success": 4, "failed": 1},
            "визит к клиенту": {"total": 2, "success": 2, "failed": 0},
        },
        "timesheet": {"hours": 160, "salary": 50000},
        "additional_payments": {"items": [
            {"description": "За результат <важно>", "amount": 1500},
            {"description": "", "amount": None},
        ]},
        "total_bonus": 19300,
    }


def chief_report(enabled_lukoil=False, debt_items=True):
    report = {
        "report_type": "chief", "employee": "Руководитель Тест Тестович",
        "profit": {"sales": 1000000, "income": 200000, "profitability": 19.95, "kpi": {
            "plan": 180000, "fact": 200000, "percent": 111.11,
            "profitability_base_percent": 18.03, "profitability_percent": 110.65,
            "income_weighted_percent": 66.67, "profitability_weighted_percent": 44.26,
            "total_percent": 110.93, "bonus_base": 10000, "bonus": 11093,
        }},
        "cycle": {"plan_count": 4, "fact_count": 5, "plan": 20, "fact": 25, "ratio": .8, "bonus_base": 50000, "bonus": 40000},
        "zic": {"brand": "ZIC", "plan": 100, "fact": 80, "percent": 80, "bonus_base": 100000, "bonus": 80000},
        "other": {"items": [{"brand": "VEGA", "percent": 80, "weight": 50, "weighted_percent": 40}], "percent": 40, "calculation_percent": 32, "bonus_base": 70000, "bonus": 22400},
        "debt": {"total": 150000, "responsibility": 1500, "threshold": 100000, "large_items": []},
        "lukoil": {"calculation_enabled": enabled_lukoil, "manager_items": [], "manager_bonus_total": 0, "coefficient": .25 if enabled_lukoil else None, "bonus": 0},
        "key_clients_profit": {"items": [{"client": "Клиент", "profit": 100000, "bonus": 10000}], "bonus": 10000},
        "timesheet": {"hours": 160, "salary": 51614.4},
        "additional_payments": {"items": [{"description": "Доплата", "amount": 1000}]},
        "total_bonus": 163000, "salary_total": 214614.4,
    }
    if debt_items:
        report["debt"]["large_items"] = [{"contractor": "Контрагент", "overdue": 150000, "comment": "Комментарий"}]
    if enabled_lukoil:
        report["lukoil"]["manager_items"] = [{"employee": "Менеджер", "manager_bonus": 1000}]
        report["lukoil"]["manager_bonus_total"] = 1000
        report["lukoil"]["bonus"] = 250
    return report


def test_all_document_generators_create_readable_files(tmp_path):
    report = manager_report()
    pdf = tmp_path / "manager.pdf"
    docx = tmp_path / "manager.docx"
    generate_pdf(pdf, report["employee"], report["profit"], report["brand"], report["debt"],
                 report["cycle"], report["communications"], report["timesheet"],
                 report["additional_payments"], 2026, 1)
    generate_docx(docx, report["employee"], report, 2026, 1)
    assert pdf.read_bytes().startswith(b"%PDF")
    assert docx.read_bytes().startswith(b"PK")


def test_chief_pdf_covers_enabled_and_disabled_optional_tables(tmp_path):
    for enabled, items in ((False, False), (True, True)):
        path = tmp_path / f"chief-{enabled}.pdf"
        generate_chief_pdf(path, chief_report(enabled, items), 2026, 1)
        assert path.stat().st_size > 1000


def test_manager_generators_empty_optional_tables_and_invalid_money(tmp_path):
    assert docx_money(object()) == "0.00"
    assert pdf_money(object()) == "0.00"
    report = manager_report()
    report["brand"]["lukoil"] = None
    report["debt"]["large_items"] = []
    generate_docx(tmp_path / "empty.docx", report["employee"], report, 2026, 2)
    generate_pdf(
        tmp_path / "empty.pdf", report["employee"], report["profit"], report["brand"],
        report["debt"], report["cycle"], report["communications"], report["timesheet"],
        report["additional_payments"], 2026, 2,
    )


def test_debt_corrections_table_wraps_comments_and_includes_totals():
    from generators.debt_adjustments import debt_adjustment_table
    debt = {"original_total": 56375.46, "adjustment_total": 1128859.39, "total": 1185234.85,
            "corrections": [{"amount": 1128859.39, "comment": "Агинское ДРСУ\n" + "Длинный комментарий " * 30}]}
    table = debt_adjustment_table(debt)[2]
    assert table._cellvalues[2][0].getPlainText().startswith("Агинское ДРСУ")
    assert table._cellvalues[2][1].getPlainText() == "1 128 859.39"
    assert table._cellvalues[-1][1].getPlainText() == "1 185 234.85"
    width, height = table.wrap(520, 800)
    assert width <= 520 and height > 100
