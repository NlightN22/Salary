from pathlib import Path
import os


WEB_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv("SALARY_DATA_DIR", WEB_DIR / "service_data"))
DEPARTMENTS_DIR = Path(os.getenv("SALARY_DEPARTMENTS_DIR", WEB_DIR.parent / "data"))
UPLOADS_DIR = DEPARTMENTS_DIR
GENERATED_DIR = DEPARTMENTS_DIR
DB_PATH = DATA_DIR / "salary.db"

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")


def department_storage_code(department: object | None) -> str:
    """Return a filesystem-safe department code for new service files."""
    value = str(getattr(department, "code", "") or "default").strip().lower()
    safe = "".join(character if character.isalnum() or character in "-_" else "-" for character in value)
    return safe.strip("-") or "default"


def department_storage_name(value: str | None) -> str:
    name = str(value or "").strip()
    safe = "".join(character if character.isalnum() or character in "-_" else "_" for character in name)
    return safe.strip("_") or "default"


def period_storage_dir(root: Path, period: object) -> Path:
    department = getattr(period, "department", None)
    name = getattr(department, "name", None)
    safe_name = department_storage_name(name) if name else department_storage_code(department)
    if not name and getattr(department, "id", None) is not None:
        safe_name = f"{safe_name}_{department.id}"
    return root / safe_name / str(getattr(period, "year")) / str(int(getattr(period, "month")))


def resolve_service_data_path(stored_path: str | Path) -> Path:
    """Resolve a department-scoped path stored in SQLite."""
    path = Path(stored_path)
    if not path.is_absolute() and path.parts and path.parts[0] == "data_root":
        return DEPARTMENTS_DIR.joinpath(*path.parts[1:])
    return path


def stored_service_data_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return str(Path("data_root") / path.resolve().relative_to(DEPARTMENTS_DIR.resolve()))
    except ValueError:
        return str(path)

MONTHS = {
    1: "январь",
    2: "февраль",
    3: "март",
    4: "апрель",
    5: "май",
    6: "июнь",
    7: "июль",
    8: "август",
    9: "сентябрь",
    10: "октябрь",
    11: "ноябрь",
    12: "декабрь",
}

REPORT_TYPES = {
    "profit": "Отчет по прибыли",
    "brand_sales": "Отчет по продажам брендов / KPI",
    "debt": "Отчет по дебиторской задолженности",
    "timesheet": "Табель рабочего времени",
    "cycle": "Отчет по циклу сделки",
    "communications": "Отчет по коммуникациям",
}

REPORT_DESCRIPTIONS = {
    "profit": {
        "description": "Отчет 1С по продажам, доходу и рентабельности.",
        "filename_hint": "profit.xls или profit.xlsx",
    },
    "brand_sales": {
        "description": "Отчет 1С по брендам, планам, факту и KPI.",
        "filename_hint": "brand_sales.xlsx",
    },
    "debt": {
        "description": "Отчет 1С по просроченной дебиторской задолженности.",
        "filename_hint": "debt.xlsx",
    },
    "timesheet": {
        "description": "Табель рабочего времени. Можно загрузить несколько файлов.",
        "filename_hint": "Табель.xlsx, Табель 2.xlsx и т.п.",
    },
    "cycle": {
        "description": "Отчет CRM по циклу сделки.",
        "filename_hint": "файл с названием, содержащим «цикл»",
    },
    "communications": {
        "description": "Отчет CRM по коммуникациям за месяц.",
        "filename_hint": "файл с названием, содержащим «коммуникации»",
    },
}

REQUIRED_REPORT_TYPES = {
    "profit",
    "brand_sales",
    "debt",
    "timesheet",
    "cycle",
    "communications",
}
