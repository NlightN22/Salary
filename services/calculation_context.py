import pandas as pd

from services.file_finder import find_files
from services.period_finder import get_latest_period
from parsers.excel_reader import read_excel
from parsers.profit_parser import ProfitParser
from parsers.brand_parser import BrandParser
from parsers.debt_parser import DebtParser
from parsers.comm_parser import CommParser
from parsers.cycle_parser import CycleParser
from parsers.timesheet_parser import TimesheetParser


REQUIRED_FILES = ("profit", "brand", "debt", "communications", "cycle", "timesheet")


def load_context():
    period_folder = get_latest_period()
    files = find_files(period_folder)
    missing = [name for name in REQUIRED_FILES if name not in files]
    if missing:
        raise FileNotFoundError("Не найдены файлы: " + ", ".join(missing))

    return load_context_from_files(
        year=int(period_folder.parent.name),
        month=int(period_folder.name),
        files=files,
    )


def load_context_from_files(year, month, files):
    normalized_files = dict(files)
    if "brand_sales" in normalized_files and "brand" not in normalized_files:
        normalized_files["brand"] = normalized_files["brand_sales"]

    missing = [name for name in REQUIRED_FILES if name not in normalized_files]
    if missing:
        raise FileNotFoundError("Не найдены файлы: " + ", ".join(missing))

    timesheet_files = normalized_files["timesheet"]
    if not isinstance(timesheet_files, (list, tuple)):
        timesheet_files = [timesheet_files]

    profit_df = read_excel(normalized_files["profit"])
    brand_df = read_excel(normalized_files["brand"])
    debt_df = read_excel(normalized_files["debt"])
    communications_df = read_excel(normalized_files["communications"])
    cycle_df = read_excel(normalized_files["cycle"])
    timesheet_frames = [read_excel(path) for path in timesheet_files]

    _require_columns(brand_df, 9, "Brand Sales")
    _require_columns(communications_df, 1, "Коммуникации")
    seen = set()
    for frame in timesheet_frames:
        _require_columns(frame, 2, "Табель")
        for _, row in frame.iterrows():
            name = str(row.iloc[0]).lower().replace(".", " ").split()
            try:
                float(str(row.iloc[1]).split("\n")[0].replace(",", ".").strip())
            except ValueError:
                continue
            if len(name) < 2:
                continue
            identity = (name[0], name[1][0])
            if identity in seen:
                raise ValueError(f"Повтор сотрудника в табелях: {row.iloc[0]}. Удалите дублирующую запись")
            seen.add(identity)

    return {
        "year": int(year),
        "month": int(month),
        "profit": ProfitParser(profit_df),
        "brand": BrandParser(brand_df),
        "debt": DebtParser(debt_df),
        "communications": CommParser(communications_df),
        "cycle": CycleParser(cycle_df),
        "timesheet": TimesheetParser(pd.concat(
            timesheet_frames, ignore_index=True
        )),
    }


def _require_columns(dataframe, minimum: int, report_name: str) -> None:
    if len(dataframe.columns) < minimum:
        raise ValueError(
            f"Отчет «{report_name}» содержит {len(dataframe.columns)} колонок; "
            f"требуется не менее {minimum}"
        )
