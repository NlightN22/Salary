from pathlib import Path

import pandas as pd
import pytest

from parsers.excel_reader import read_excel


def test_reads_xlsx_with_unicode(tmp_path):
    path = tmp_path / "Отчёт_日本語.xlsx"
    pd.DataFrame({"Колонка": ["значение"]}).to_excel(path, index=False)
    assert read_excel(path).iloc[0, 0] == "значение"


def test_missing_file_has_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError, match="Файл не найден"):
        read_excel(tmp_path / "missing.xlsx")


def test_directory_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="указан каталог"):
        read_excel(tmp_path)


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "empty.xlsx"
    path.touch()
    with pytest.raises(ValueError, match="Файл пуст"):
        read_excel(path)


@pytest.mark.parametrize("payload", [b"not an excel file", b"\xff\xfe\x00bad encoding"])
def test_corrupted_or_wrongly_encoded_file_is_rejected(tmp_path, payload):
    path = tmp_path / "broken.xlsx"
    path.write_bytes(payload)
    with pytest.raises(ValueError, match="Не удалось прочитать Excel-файл"):
        read_excel(path)


def test_header_only_workbook_is_rejected(tmp_path):
    path = tmp_path / "headers.xlsx"
    pd.DataFrame(columns=["A", "B"]).to_excel(path, index=False)
    with pytest.raises(ValueError, match="нет строк"):
        read_excel(path)
