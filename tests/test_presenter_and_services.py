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
from services.report_io import load_reports, report_stem, save_report
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
    period.mkdir(parents=True)
    (tmp_path / "Data" / "B2B-направление" / "2025" / "11").mkdir(parents=True)
    (tmp_path / "Data" / "2027" / "1").mkdir(parents=True)
    names = ["profit.xlsx", "brand.xlsx", "debt.xlsx", "Коммуникации.xlsx", "Цикл.xlsx", "Табель 2.xlsx", "Табель 1.xlsx", "other.txt"]
    for name in names:
        (period / name).touch()
    files = find_files(period)
    assert set(files) == {"profit", "brand", "debt", "communications", "cycle", "timesheet"}
    assert [path.name for path in files["timesheet"]] == ["Табель 1.xlsx", "Табель 2.xlsx"]
    assert get_latest_period(tmp_path / "Data", department="B2B-направление") == period


def test_latest_period_never_falls_back_to_unscoped_data(tmp_path):
    (tmp_path / "Data" / "2027" / "1").mkdir(parents=True)
    with pytest.raises(FileNotFoundError, match="подразделения"):
        get_latest_period(tmp_path / "Data", department="B2B-направление")


def test_report_io_roundtrip_and_safe_filename(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    report = {"employee": "Иванов/Опасный Имя Отчество", "value": 1}
    path = save_report(report, 2026, 1, "B2B-направление")
    assert "/" not in path.name
    other_path = save_report(report, 2026, 1, "Другое подразделение")
    assert other_path.parent != path.parent
    assert other_path.exists()
    assert [item[0] for item in load_reports(2026, 1, "Другое подразделение")] == [other_path]
    assert [item[0] for item in load_reports(2026, 1, "B2B-направление")] == [path]
    assert report_stem("Иванов:Тест Имя", 2026, 1).startswith("Иванов_Тест")
    loaded = load_reports(2026, 1, "B2B-направление")
    assert loaded[0][1] == report


def test_report_io_rejects_nan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError):
        save_report({"employee": "Иванов Иван", "value": float("nan")}, 2026, 1, "B2B-направление")
