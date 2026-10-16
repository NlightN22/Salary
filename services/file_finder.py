from pathlib import Path


def find_files(folder):
    folder = Path(folder)
    reports_folder = folder / "reports"
    if reports_folder.is_dir():
        folder = reports_folder
    files = {}
    timesheets = []

    for file in sorted(Path(folder).iterdir(), key=lambda path: path.name.casefold()):
        if not file.is_file() or file.name.startswith((".", "~$")):
            continue

        name = file.name.lower()

        report_type = None
        if "profit" in name:
            report_type = "profit"
        elif "debt" in name:
            report_type = "debt"
        elif "brand" in name:
            report_type = "brand"
        elif "коммуникации" in name or "communication" in name:
            report_type = "communications"
        elif "цикл" in name or "cycle" in name:
            report_type = "cycle"
        elif "табель" in name or "timesheet" in name:
            timesheets.append(file)
        if report_type:
            if report_type in files:
                raise ValueError(
                    f"Найдено несколько файлов отчета {report_type}: "
                    f"{files[report_type].name}, {file.name}"
                )
            files[report_type] = file

    if timesheets:
        files["timesheet"] = sorted(timesheets)

    return files
