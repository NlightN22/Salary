import json
from pathlib import Path

import pytest

from salary_web.snapshot_presenter import (
    build_final_summary_rows,
    build_snapshot_sections,
)
from salary_web.ui_helpers import report_type_label, status_label
from services.file_finder import find_files
from services.period_finder import get_latest_period
from services.report_naming import report_stem
from tests.test_generators import chief_report, manager_report


def test_presenter_formats_complete_manager_and_chief_snapshots():
    manager = manager_report()
    manager["report_type"] = "manager"
    manager["salary_total"] = 70000
    manager["manual_adjustments"] = [{"comment": "x"}]
    sections = build_snapshot_sections(manager)
    assert {section["code"] for section in sections} >= {"profit", "brand", "debt", "communications"}
    debt = next(section for section in sections if section["code"] == "debt")
    assert debt["debt_large_items"][0]["contractor"] == "Клиент <А>"
    assert any(row["style"] == "salary" for row in build_final_summary_rows(manager))

    chief = chief_report()
    sections = build_snapshot_sections(chief)
    lukoil = next(section for section in sections if section["code"] == "lukoil")
    assert lukoil["hide_field_table"] and not lukoil["can_adjust"]
    clients = next(section for section in sections if section["code"] == "key_clients_profit")
    assert clients["key_client_items"][0]["profit"] == "100 000"
    assert len(build_final_summary_rows(chief)) == 11


def test_presenter_handles_empty_unknown_and_fallback_values():
    assert build_snapshot_sections({}) == []
    assert build_final_summary_rows({}) == []
    snapshot = {
        "report_type": "unknown", "total_bonus": "bad", "employee": "X",
        "timesheet": {"salary": 10}, "custom_section": {
            "some_field": True, "none": None, "ratio": .5,
            "items": [{"long_name": "text"}, 2],
        },
        "debt": {"large_items": "bad"},
        "key_clients_profit": {"items": None},
    }
    sections = build_snapshot_sections(snapshot)
    assert sections
    assert status_label("mystery") == "mystery"
    assert report_type_label("mystery") == "mystery"


def test_file_finder_and_latest_period(tmp_path):
    period = tmp_path / "Data" / "B2B-направление" / "2026" / "12"
    reports = period / "reports"
    reports.mkdir(parents=True)
    (tmp_path / "Data" / "B2B-направление" / "2025" / "11").mkdir(parents=True)
    (tmp_path / "Data" / "2027" / "1").mkdir(parents=True)
    names = ["profit.xlsx", "brand.xlsx", "debt.xlsx", "Коммуникации.xlsx", "Цикл.xlsx", "Табель 2.xlsx", "Табель 1.xlsx", "other.txt"]
    for name in names:
        (reports / name).touch()
    (reports / "__init__.py").touch()
    files = find_files(period)
    assert set(files) == {"profit", "brand", "debt", "communications", "cycle", "timesheet"}
    assert [path.name for path in files["timesheet"]] == ["Табель 1.xlsx", "Табель 2.xlsx"]
    assert get_latest_period(tmp_path / "Data", department="B2B-направление") == period


def test_file_finder_rejects_duplicate_source_reports(tmp_path):
    reports = tmp_path / "2026" / "6" / "reports"
    reports.mkdir(parents=True)
    (reports / "profit.xlsx").touch()
    (reports / "profit-final.xlsx").touch()
    with pytest.raises(ValueError, match="несколько файлов"):
        find_files(reports.parent)


def test_file_finder_recognizes_canonical_web_upload_names(tmp_path):
    reports = tmp_path / "reports"
    reports.mkdir()
    names = ("profit.xlsx", "brand_sales.xlsx", "debt.xlsx", "communications.xlsx",
             "cycle.xlsx", "timesheet_1.xlsx", "timesheet_2.xlsx")
    for name in names:
        (reports / name).touch()
    files = find_files(tmp_path)
    assert set(files) == {"profit", "brand", "debt", "communications", "cycle", "timesheet"}
    assert [path.name for path in files["timesheet"]] == ["timesheet_1.xlsx", "timesheet_2.xlsx"]


def test_latest_period_never_falls_back_to_unscoped_data(tmp_path):
    (tmp_path / "Data" / "2027" / "1").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="подразделения"):
        get_latest_period(tmp_path / "Data", department="B2B-направление")


def test_latest_period_uses_department_name_as_folder(tmp_path):
    period = tmp_path / "data" / "B2B-направление" / "2026" / "8"
    (period / "reports").mkdir(parents=True)
    assert get_latest_period(tmp_path / "data", department="B2B-направление") == period


def test_file_and_period_finders_ignore_temporary_files_and_report_missing_paths(tmp_path):
    reports = tmp_path / "files"
    reports.mkdir()
    (reports / ".hidden.xlsx").touch()
    (reports / "~$temporary.xlsx").touch()
    assert find_files(reports) == {}

    (tmp_path / "B2B").mkdir()
    with pytest.raises(FileNotFoundError, match="нет папок с годами"):
        get_latest_period(tmp_path, department="B2B")

    department_dir = tmp_path / "B2B"
    (department_dir / "2026").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="нет папок с месяцами"):
        get_latest_period(tmp_path, department="B2B")

    with pytest.raises(ValueError, match="Некорректное название"):
        get_latest_period(tmp_path, department="../B2B")


def test_report_stem_uses_full_safe_name_month_and_year():
    assert report_stem("Иванов/Иван Иванович", 2026, 10) == "Иванов_Иван_Иванович_октябрь_2026"
    assert report_stem("Иванов Петр Петрович", 2026, 10) != report_stem("Иванов Иван Иванович", 2026, 10)
