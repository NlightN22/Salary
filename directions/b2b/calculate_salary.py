"""Calculate the latest B2B period and generate employee PDFs in memory."""

from directions.b2b.chief_salary import calculate_chief
from directions.b2b.config import DEPARTMENT_NAME
from directions.b2b.manager_salary import calculate_managers
from services.calculation_context import load_context
from services.report_naming import report_stem
from generators.chief_pdf_generator import generate_chief_pdf
from generators.pdf_generator import generate_pdf


def main():
    context = load_context(DEPARTMENT_NAME)
    managers = calculate_managers(context)
    reports = [*managers, calculate_chief(context, managers)]
    output_dir = context["period_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)
    for report in reports:
        path = output_dir / f"{report_stem(report['employee'], context['year'], context['month'])}.pdf"
        if report.get("report_type") == "chief":
            generate_chief_pdf(path, report, context["year"], context["month"])
        else:
            generate_pdf(
                path, report["employee"], report["profit"], report["brand"],
                report["debt"], report["cycle"], report["communications"],
                report["timesheet"], report["additional_payments"],
                context["year"], context["month"],
            )
        print(f"Создан PDF: {path}")
    print(f"PDF-файлов создано: {len(reports)}")


if __name__ == "__main__":  # pragma: no cover - exercised as a process entry point
    main()
