from pathlib import Path

import pytest

import calculate_salary as root_calculate
import main as root_render
import directions.b2b.calculate_salary as calculate_module
import directions.b2b.manager_salary as manager_module
import directions.b2b.render_pdfs as render_module
from models.employee_report import BrandKPI, DebtItem, EmployeeReport


def test_compatibility_entrypoints_delegate(monkeypatch):
    calls = []
    monkeypatch.setattr(root_calculate, "main", lambda: calls.append("calculate"))
    monkeypatch.setattr(root_render, "main", lambda: calls.append("render"))
    root_calculate.main()
    root_render.main()
    assert calls == ["calculate", "render"]


def test_calculate_salary_main_saves_manager_and_chief(monkeypatch, capsys):
    context = {"year": 2026, "month": 1}
    saved = []
    monkeypatch.setattr(calculate_module, "load_context", lambda department: context)
    monkeypatch.setattr(calculate_module, "calculate_managers", lambda value: [{"employee": "Manager"}])
    monkeypatch.setattr(calculate_module, "calculate_chief", lambda value, managers: {"employee": "Chief"})
    monkeypatch.setattr(calculate_module, "save_report", lambda report, year, month, department: saved.append(report) or Path(report["employee"] + ".json"))
    calculate_module.main()
    assert [item["employee"] for item in saved] == ["Manager", "Chief"]
    assert "JSON-файлов создано: 2" in capsys.readouterr().out


def test_manager_main_saves_each_report(monkeypatch, capsys):
    context = {"year": 2026, "month": 1}
    monkeypatch.setattr(manager_module, "load_context", lambda department: context)
    monkeypatch.setattr(manager_module, "calculate_managers", lambda value: [{"employee": "Manager", "report_type": "manager"}])
    monkeypatch.setattr(manager_module, "save_report", lambda *args: Path("manager.json"))
    manager_module.main()
    assert "Создан JSON менеджера" in capsys.readouterr().out


def test_render_pdfs_main_all_report_types(monkeypatch, tmp_path, capsys):
    period = tmp_path / "2026" / "1"
    period.mkdir(parents=True)
    reports = [
        (period / "chief.json", {"employee": "Chief", "report_type": "chief"}),
        (period / "manager.json", {
            "employee": "Manager", "report_type": "manager", "profit": {}, "brand": {},
            "debt": {}, "cycle": {}, "communications": {}, "timesheet": {}, "additional_payments": {},
        }),
    ]
    calls = []
    monkeypatch.setattr(render_module, "get_latest_period", lambda **kwargs: period)
    monkeypatch.setattr(render_module, "load_reports", lambda year, month, department: reports)
    monkeypatch.setattr(render_module, "generate_chief_pdf", lambda *args: calls.append("chief"))
    monkeypatch.setattr(render_module, "generate_pdf", lambda *args: calls.append("manager"))
    render_module.main()
    assert calls == ["chief", "manager"]
    assert capsys.readouterr().out.count("Создан PDF") == 2


def test_render_pdfs_rejects_empty_and_unknown_reports(monkeypatch, tmp_path):
    period = tmp_path / "2026" / "1"
    period.mkdir(parents=True)
    monkeypatch.setattr(render_module, "get_latest_period", lambda **kwargs: period)
    monkeypatch.setattr(render_module, "load_reports", lambda *args: [])
    with pytest.raises(FileNotFoundError, match="JSON-файлы"):
        render_module.main()
    monkeypatch.setattr(render_module, "load_reports", lambda *args: [(period / "bad.json", {"employee": "X", "report_type": "bad"})])
    with pytest.raises(ValueError, match="Неизвестный тип"):
        render_module.main()


def test_legacy_dataclasses_are_constructible():
    brand = BrandKPI("ZIC", 1, 2, 200, 10)
    debt = DebtItem("Client", 100)
    report = EmployeeReport("Employee", brands=[brand], debts=[debt])
    assert report.brands[0].bonus == 10
    assert report.debts[0].contractor == "Client"
