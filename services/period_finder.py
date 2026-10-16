from pathlib import Path


def get_latest_period(data_root="data", *, department):
    component = department_path_component(department)
    department_dir = Path(data_root) / component
    if not department_dir.is_dir():
        raise FileNotFoundError(f"Не найдена папка данных подразделения: {department_dir}")

    years = [
        int(x.name)
        for x in department_dir.iterdir()
        if x.is_dir() and x.name.isdigit()
    ]
    if not years:
        raise FileNotFoundError(f"В папке подразделения нет папок с годами: {department_dir}")

    latest_year = max(years)

    months_path = department_dir / str(latest_year)

    months = [
        int(x.name)
        for x in months_path.iterdir()
        if x.is_dir() and x.name.isdigit()
    ]
    if not months:
        raise FileNotFoundError(f"В папке {months_path} нет папок с месяцами")

    latest_month = max(months)

    return months_path / str(latest_month)


def department_path_component(department):
    value = str(department or "").strip()
    if (
        not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise ValueError("Некорректное название подразделения для каталога")
    return value
