import pandas as pd
from pathlib import Path


def read_excel(file_path):
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Файл не найден: {path}")
    if not path.is_file():
        raise ValueError(f"Ожидался файл, но указан каталог: {path}")
    if path.stat().st_size == 0:
        raise ValueError(f"Файл пуст: {path}")

    engines = ("xlrd", "openpyxl") if path.suffix.lower() == ".xls" else ("openpyxl", "xlrd")
    errors = []
    for engine in engines:
        try:
            dataframe = pd.read_excel(path, engine=engine)
            if dataframe.empty:
                raise ValueError("в книге нет строк с данными")
            return dataframe
        except Exception as error:
            errors.append(f"{engine}: {error}")

    details = "; ".join(errors)
    raise ValueError(f"Не удалось прочитать Excel-файл {path.name}. {details}")
