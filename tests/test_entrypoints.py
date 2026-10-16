import calculate_salary as root_calculate
import main as root_main
import directions.b2b.calculate_salary as calculate_module
from models.employee_report import BrandKPI, DebtItem, EmployeeReport


def test_compatibility_entrypoints_delegate(monkeypatch):
    calls = []
    monkeypatch.setattr(root_calculate, "main", lambda: calls.append("calculate"))
    monkeypatch.setattr(root_main, "main", lambda: calls.append("main"))
    root_calculate.main()
    root_main.main()
    assert calls == ["calculate", "main"]


def test_calculate_salary_generates_manager_and_chief_pdfs(monkeypatch, tmp_path, capsys):
    context = {"year": 2026, "month": 1, "period_dir": tmp_path}
    manager = {
        "employee": "Manager", "report_type": "manager", "profit": {}, "brand": {},
        "debt": {}, "cycle": {}, "communications": {}, "timesheet": {},
        "additional_payments": {},
    }
    chief = {"employee": "Chief", "report_type": "chief"}
    monkeypatch.setattr(calculate_module, "load_context", lambda _department: context)
    monkeypatch.setattr(calculate_module, "calculate_managers", lambda _context: [manager])
    monkeypatch.setattr(calculate_module, "calculate_chief", lambda _context, _managers: chief)
    monkeypatch.setattr(calculate_module, "report_stem", lambda employee, year, month: f"{employee}_{year}_{month}")
    generated = []
    monkeypatch.setattr(calculate_module, "generate_pdf", lambda path, *args: generated.append(("manager", path)))
    monkeypatch.setattr(calculate_module, "generate_chief_pdf", lambda path, *args: generated.append(("chief", path)))

    calculate_module.main()

    assert [(kind, path.name) for kind, path in generated] == [
        ("manager", "Manager_2026_1.pdf"),
        ("chief", "Chief_2026_1.pdf"),
    ]
    assert all(path.parent == tmp_path for _, path in generated)
    assert "PDF-файлов создано: 2" in capsys.readouterr().out


def test_legacy_dataclasses_are_constructible():
    brand = BrandKPI("ZIC", 1, 2, 200, 10)
    debt = DebtItem("Client", 100)
    report = EmployeeReport("Employee", brands=[brand], debts=[debt])
    assert report.brands[0].bonus == 10
    assert report.debts[0].contractor == "Client"
