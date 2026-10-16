"""Generate final PDF calculation sheets exclusively from saved JSON files."""

from generators.chief_pdf_generator import generate_chief_pdf
from generators.pdf_generator import generate_pdf
from directions.b2b.config import DEPARTMENT_NAME
from services.period_finder import get_latest_period
from services.report_io import load_reports, report_stem


def main():
    period = get_latest_period(department=DEPARTMENT_NAME)
    year, month = int(period.parent.name), int(period.name)
    reports = load_reports(year, month, DEPARTMENT_NAME)
    if not reports:
        raise FileNotFoundError("JSON-файлы расчетов не найдены. Сначала запустите calculate_salary.py")
    for json_path, report in reports:
        pdf_path = json_path.parent / f"{report_stem(report['employee'], year, month)}.pdf"
        if report.get("report_type") == "chief":
            generate_chief_pdf(pdf_path, report, year, month)
        elif report.get("report_type") == "manager":
            generate_pdf(pdf_path, report["employee"], report["profit"], report["brand"], report["debt"],
                         report["cycle"], report["communications"], report["timesheet"],
                         report["additional_payments"], year, month)
        else:
            raise ValueError(f"Неизвестный тип отчета в {json_path.name}")
        print(f"Создан PDF: {pdf_path}")


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    main()
