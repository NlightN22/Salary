import json
from pathlib import Path


MONTHS = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def report_directory(year, month):
    path = Path("Report") / str(year) / str(month)
    path.mkdir(parents=True, exist_ok=True)
    return path


def report_stem(employee, year, month):
    full_name = "_".join(str(employee).split())
    safe_name = full_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    return f"{safe_name}_{MONTHS[month]}_{year}"


def save_report(report, year, month):
    path = report_directory(year, month) / f"{report_stem(report['employee'], year, month)}.json"
    with path.open("w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return path


def load_reports(year, month):
    folder = report_directory(year, month)
    reports = []
    for path in sorted(folder.glob("*.json")):
        with path.open(encoding="utf-8") as stream:
            reports.append((path, json.load(stream)))
    return reports
