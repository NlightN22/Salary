SECTION_TITLES = {
    "general": "Общие данные",
    "profit": "Доход",
    "brand": "KPI брендов",
    "zic": "ZIC",
    "other": "Спец. продукты",
    "debt": "Просроченная дебиторская задолженность",
    "communications": "Коммуникации",
    "cycle": "Цикл сделки",
    "timesheet": "Оклад",
    "lukoil": "Лукойл",
    "key_clients_profit": "Чистая прибыль по ключевым клиентам",
    "additional_payments": "Дополнительные выплаты",
    "manual_adjustments": "Ручные корректировки",
}

GENERAL_FIELDS = ("employee", "report_type", "total_bonus", "salary_total")
HIDDEN_SECTIONS = {"additional_payments", "manual_adjustments"}
READONLY_SECTIONS = {"general", "communications"}

FIELD_TITLES = {
    "corrections": "Корректировки суммы ПДЗ",
    "original_total": "ПДЗ по исходному отчету",
    "adjustment_total": "Корректировка суммы ПДЗ",
    "kpi": "KPI",
    "brand": "Бренд",
    "employee": "Сотрудник",
    "report_type": "Тип расчетки",
    "total_bonus": "ИТОГО премия",
    "salary_total": "Размер заработной платы",
    "sales": "Сумма продаж",
    "income": "Доход",
    "profitability": "Рентабельность",
    "bonus": "Размер бонуса",
    "zic": "ZIC",
    "lukoil": "Лукойл",
    "other": "Спец. продукты",
    "zic_bonus_total": "Бонус KPI ZIC",
    "lukoil_bonus": "Бонус Лукойл",
    "other_bonus_total": "Бонус за другие KPI",
    "bonus_total": "Итого бонус по брендам",
    "total": "Итого",
    "responsibility": "Ответственность",
    "ratio": "Соотношение",
    "threshold": "Порог задолженности",
    "large_items": "Клиенты с задолженностью 100 000 и более",
    "contractor_column_found": "Колонка контрагента найдена",
    "plan": "План",
    "fact": "Факт",
    "plan_count": "Количество сделок в плане",
    "fact_count": "Количество сделок в факте",
    "plan_days_sum": "Сумма дней по плану",
    "fact_days_sum": "Сумма дней по факту",
    "hours": "Отработано часов",
    "salary": "Оклад",
    "items": "Строки",
    "description": "Описание",
    "amount": "Сумма",
    "comment": "Комментарий",
    "client": "Клиент",
    "profit": "Прибыль",
    "contractor": "Контрагент",
    "debt": "Задолженность",
    "overdue": "Сумма задолженности",
    "bonus_base": "Базовый размер бонуса",
    "income_weight": "Вес дохода",
    "income_weighted_percent": "Доход с учетом веса",
    "profitability_base_percent": "Базовая рентабельность",
    "profitability_percent": "Выполнение по рентабельности",
    "profitability_weight": "Вес рентабельности",
    "profitability_weighted_percent": "Рентабельность с учетом веса",
    "total_percent": "Итоговое выполнение",
    "weighted_percent": "Выполнение с учетом веса",
    "calculation_percent": "Процент для расчета",
    "responsibility_percent": "Процент ответственности",
    "bonus_percent": "Процент бонуса",
    "base": "База",
    "weight": "Вес",
}


def build_snapshot_sections(snapshot: dict) -> list[dict[str, object]]:
    if not snapshot:
        return []

    sections = []
    for key, value in snapshot.items():
        if key in GENERAL_FIELDS or key in HIDDEN_SECTIONS:
            continue
        visible_value = _section_visible_value(key, value)
        section = {
            "code": key,
            "title": SECTION_TITLES.get(key, key),
            "rows": _flatten_value(visible_value),
            "can_adjust": key not in READONLY_SECTIONS,
        }
        if key == "lukoil" and isinstance(value, dict) and not value.get("calculation_enabled", True):
            section["hide_field_table"] = True
            section["can_adjust"] = False
            section["lukoil_calculation_disabled"] = True
        if key == "debt":
            section["debt_large_items"] = _debt_large_items(value)
        if key == "key_clients_profit":
            section["key_client_items"] = _key_client_items(value)
        sections.append(section)
    return sections


def build_summary_rows(snapshot: dict) -> list[dict[str, str]]:
    return [
        {"field": _field_title(field), "value": _format_value(snapshot.get(field), field)}
        for field in ("report_type", "total_bonus", "salary_total")
        if field in snapshot
    ]


def build_final_summary_rows(snapshot: dict) -> list[dict[str, str]]:
    if not snapshot:
        return []

    if snapshot.get("report_type") == "chief":
        rows = [
            _summary_row("Бонус за прибыль", snapshot.get("profit", {}).get("kpi", {}).get("bonus")),
            _summary_row("Бонус за цикл сделки", snapshot.get("cycle", {}).get("bonus")),
            _summary_row("Бонус KPI ZIC", snapshot.get("zic", {}).get("bonus")),
            _summary_row("Бонус за спец продукты", snapshot.get("other", {}).get("bonus")),
            _summary_row("Бонус Лукойл", snapshot.get("lukoil", {}).get("bonus")),
            _summary_row(
                "Чистая прибыль по ключевым клиентам",
                snapshot.get("key_clients_profit", {}).get("bonus"),
            ),
            _summary_row("Ответственность за ПДЗ", -_numeric(snapshot.get("debt", {}).get("responsibility"))),
            _summary_row("Дополнительные выплаты", snapshot.get("additional_payments", {}).get("total")),
            _summary_row("ИТОГО, премия за месяц к выплате", snapshot.get("total_bonus"), "total"),
            _summary_row("Отработано часов", snapshot.get("timesheet", {}).get("hours"), decimals=2),
            _summary_row("Оклад", snapshot.get("timesheet", {}).get("salary")),
            _summary_row("Размер заработной платы", _salary_total(snapshot), "salary"),
        ]
    else:
        rows = [
            _summary_row("Бонус от дохода 5%", snapshot.get("profit", {}).get("bonus")),
            _summary_row("Бонус KPI ZIC", snapshot.get("brand", {}).get("zic_bonus_total")),
            _summary_row("Бонус Лукойл", snapshot.get("brand", {}).get("lukoil_bonus")),
            _summary_row("Бонус за другие KPI", snapshot.get("brand", {}).get("other_bonus_total")),
            _summary_row("Ответственность за ПДЗ", -_numeric(snapshot.get("debt", {}).get("responsibility"))),
            _summary_row("Бонус за цикл сделки", snapshot.get("cycle", {}).get("bonus")),
            _summary_row("Дополнительные выплаты", snapshot.get("additional_payments", {}).get("total")),
            _summary_row("ИТОГО, премия за месяц к выплате", snapshot.get("total_bonus"), "total"),
            _summary_row("Отработано часов", snapshot.get("timesheet", {}).get("hours"), decimals=2),
            _summary_row("Оклад", snapshot.get("timesheet", {}).get("salary")),
            _summary_row("Размер заработной платы", _salary_total(snapshot), "salary"),
        ]

    return [row for row in rows if row["value"] != ""]


def _summary_row(
    label: str,
    value,
    style: str = "",
    decimals: int = 2,
) -> dict[str, str]:
    return {
        "label": label,
        "value": _format_number(value, "", decimals) if isinstance(value, (int, float)) else _format_value(value),
        "style": style,
    }


def _numeric(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _salary_total(snapshot: dict):
    if snapshot.get("salary_total") is not None:
        return snapshot.get("salary_total")
    if snapshot.get("total_bonus") is None:
        return None
    return _numeric(snapshot.get("total_bonus")) + _numeric(snapshot.get("timesheet", {}).get("salary"))


def _section_visible_value(key: str, value):
    if key == "debt" and isinstance(value, dict):
        return {
            item_key: item_value
            for item_key, item_value in value.items()
            if item_key != "large_items"
        }
    if key == "key_clients_profit" and isinstance(value, dict):
        visible = {
            item_key: item_value
            for item_key, item_value in value.items()
            if item_key != "items"
        }
        if visible.get("bonus_percent") is not None:
            visible["bonus_percent"] = _numeric(visible["bonus_percent"]) * 100
        return visible
    if key == "lukoil" and isinstance(value, dict) and not value.get("calculation_enabled", True):
        return {}
    return value


def _key_client_items(value) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    result = []
    for item in value.get("items") or []:
        if not isinstance(item, dict):
            continue
        if not item.get("client") and item.get("profit") is None and item.get("bonus") is None:
            continue
        result.append({
            "client": str(item.get("client") or ""),
            "profit": _format_value(item.get("profit"), "profit"),
            "bonus": _format_value(item.get("bonus"), "bonus"),
        })
    return result


def _debt_large_items(value) -> list[dict[str, str]]:
    if not isinstance(value, dict):
        return []
    result = []
    for index, item in enumerate(value.get("large_items") or []):
        if not isinstance(item, dict):
            continue
        result.append({
            "index": index,
            "number": str(index + 1),
            "contractor": str(item.get("contractor") or ""),
            "overdue": _format_value(item.get("overdue"), "overdue"),
            "comment": str(item.get("comment") or ""),
        })
    return result


def _flatten_value(value, prefix: str = "") -> list[dict[str, str]]:
    rows = []
    if isinstance(value, dict):
        if not value:
            return [{"field": _field_title(prefix) if prefix else "Значение", "value": ""}]
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            rows.extend(_flatten_value(item, path))
        return rows

    if isinstance(value, list):
        if not value:
            return [{"field": _field_title(prefix) if prefix else "Список", "value": ""}]
        for index, item in enumerate(value, start=1):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            rows.extend(_flatten_value(item, path))
        return rows

    return [{"field": _field_title(prefix) if prefix else "Значение", "value": _format_value(value, prefix)}]


def _field_title(path: str) -> str:
    if path in FIELD_TITLES:
        return FIELD_TITLES[path]
    parts = []
    for part in str(path).split("."):
        if "[" in part:
            name, index = part.split("[", 1)
            index = index.rstrip("]")
            translated = FIELD_TITLES.get(name, _humanize(name))
            parts.append(f"{translated} {index}")
        else:
            parts.append(FIELD_TITLES.get(part, _humanize(part)))
    return " / ".join(parts)


def _humanize(value: str) -> str:
    return str(value).replace("_", " ").strip().capitalize()


def _format_value(value, path: str = "") -> str:
    if value is None:
        return ""
    if value == "manager":
        return "Менеджер"
    if value == "chief":
        return "Руководитель"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, int) and not isinstance(value, bool):
        return _format_number(value, path, decimals=0)
    if isinstance(value, float):
        return _format_number(value, path, decimals=2)
    return str(value)


def _format_number(value: int | float, path: str, decimals: int) -> str:
    formatted = f"{float(value):,.{decimals}f}".replace(",", " ")
    if _is_percent_field(path):
        return f"{formatted}%"
    return formatted


def _is_percent_field(path: str) -> bool:
    last_part = str(path).split(".")[-1]
    if "[" in last_part:
        last_part = last_part.split("[", 1)[0]
    return (
        "percent" in last_part
        or last_part in {"profitability", "ratio", "margin"}
    )
