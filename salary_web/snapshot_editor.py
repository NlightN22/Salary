import json
from pathlib import Path

from sqlalchemy.orm import Session

from generators.chief_pdf_generator import generate_chief_pdf
from generators.pdf_generator import generate_pdf
from services.report_io import report_stem
from services.rounding import round_half_up
from directions.b2b.config import OVERDUE_DEBT_PERCENT, CHIEF_OVERDUE_DEBT_PERCENT
from salary_web.config import GENERATED_DIR, period_storage_dir, stored_service_data_path
from salary_web.models import Calculation


def load_snapshot(calculation: Calculation) -> dict:
    if not calculation.snapshot_json:
        raise ValueError("У расчета еще нет JSON-снимка")
    return json.loads(calculation.snapshot_json)


def save_snapshot(calculation: Calculation, report: dict) -> None:
    _normalize_additional_payments(report)
    _normalize_key_clients_profit(report)
    _normalize_chief_lukoil(report)
    _recalculate_totals(report)
    calculation.snapshot_json = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    calculation.status = "edited"
    calculation.pdf_path = None


def refresh_calculated_values(calculation: Calculation) -> bool:
    """Refresh derived values stored in an existing calculation snapshot."""
    report = load_snapshot(calculation)
    before = json.dumps(report, ensure_ascii=False, sort_keys=True)
    _normalize_key_clients_profit(report)
    _normalize_chief_lukoil(report)
    _recalculate_totals(report)
    after = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if before == after:
        return False
    calculation.snapshot_json = json.dumps(
        report,
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )
    calculation.status = "edited"
    calculation.pdf_path = None
    return True


def save_snapshot_text(calculation: Calculation, snapshot_text: str) -> None:
    try:
        report = json.loads(
            snapshot_text,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"недопустимое числовое значение {value}")
            ),
        )
        if not isinstance(report, dict):
            raise ValueError("корневое значение должно быть объектом")
    except (json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"JSON заполнен некорректно: {error}") from error
    save_snapshot(calculation, report)


def update_debt_large_item_comment(
    calculation: Calculation,
    item_index: int,
    comment: str,
) -> None:
    report = load_snapshot(calculation)
    large_items = report.setdefault("debt", {}).setdefault("large_items", [])
    if item_index < 0 or item_index >= len(large_items):
        raise ValueError("Строка ПДЗ не найдена")
    large_items[item_index]["comment"] = comment
    save_snapshot(calculation, report)


def append_additional_payment(calculation: Calculation, description: str, amount: float) -> None:
    report = load_snapshot(calculation)
    additional_payments = report.setdefault("additional_payments", {})
    items = additional_payments.setdefault("items", [])
    _append_or_fill_empty_payment(items, description, amount)
    save_snapshot(calculation, report)


def update_additional_payment(
    calculation: Calculation,
    old_description: str,
    old_amount: float,
    new_description: str,
    new_amount: float,
) -> None:
    report = load_snapshot(calculation)
    items = report.setdefault("additional_payments", {}).setdefault("items", [])
    item = _find_payment_item(items, old_description, old_amount)
    if item is None:
        _append_or_fill_empty_payment(items, new_description, new_amount)
    else:
        item["description"] = new_description
        item["amount"] = new_amount
    save_snapshot(calculation, report)


def remove_additional_payment(
    calculation: Calculation,
    description: str,
    amount: float,
) -> None:
    report = load_snapshot(calculation)
    items = report.setdefault("additional_payments", {}).setdefault("items", [])
    item = _find_payment_item(items, description, amount)
    if item is not None:
        items.remove(item)
    save_snapshot(calculation, report)


def _append_or_fill_empty_payment(items: list[dict], description: str, amount: float) -> None:
    for item in items:
        if not item.get("description") and item.get("amount") is None:
            item["description"] = description
            item["amount"] = amount
            return
    items.append({"description": description, "amount": amount})


def _find_payment_item(items: list[dict], description: str, amount: float) -> dict | None:
    for item in items:
        if _text_matches(item.get("description"), description) and _amount_matches(item.get("amount"), amount):
            return item
    return None


def _text_matches(left: object, right: object) -> bool:
    return str(left or "").strip() == str(right or "").strip()


def _amount_matches(left: object, right: object) -> bool:
    try:
        return abs(float(left or 0) - float(right or 0)) < 0.005
    except (TypeError, ValueError):
        return False


def _normalize_additional_payments(report: dict) -> None:
    additional_payments = report.setdefault("additional_payments", {})
    items = additional_payments.setdefault("items", [])
    filled_items = [
        item for item in items
        if item.get("description") or item.get("amount") is not None
    ]
    empty_rows_count = max(2 - len(filled_items), 0)
    additional_payments["items"] = filled_items + [
        {"description": "", "amount": None}
        for _ in range(empty_rows_count)
    ]


def _normalize_key_clients_profit(report: dict) -> None:
    if report.get("report_type") != "chief":
        return
    section = report.setdefault("key_clients_profit", {})
    items = section.setdefault("items", [])
    filled_items = [item for item in items if _key_client_item_filled(item)]
    for item in filled_items:
        if item.get("profit") is not None:
            item["bonus"] = _key_client_bonus(section, float(item["profit"]))
    section["items"] = filled_items or [{"client": "", "profit": None, "bonus": None}]
    section["bonus"] = round_half_up(sum(float(item.get("bonus") or 0) for item in filled_items))


def _normalize_chief_lukoil(report: dict) -> None:
    if report.get("report_type") != "chief":
        return
    section = report.setdefault("lukoil", {})
    section.update({
        "calculation_enabled": False,
        "manager_items": [],
        "manager_bonus_total": 0.0,
        "coefficient": None,
        "bonus": 0.0,
    })


def append_adjustment(
    calculation: Calculation,
    section_code: str,
    adjustment_type: str,
    amount: float,
    comment: str,
) -> None:
    report = load_snapshot(calculation)
    adjustments = report.setdefault("manual_adjustments", [])
    adjustments.append({
        "section_code": section_code,
        "adjustment_type": adjustment_type,
        "amount": amount,
        "comment": comment,
    })

    additional_payments = report.setdefault("additional_payments", {})
    items = additional_payments.setdefault("items", [])
    description_parts = []
    if comment:
        description_parts.append(comment)
    else:
        description_parts.append("Корректировка")
    _append_or_fill_empty_payment(
        items,
        " / ".join(part for part in description_parts if part),
        amount,
    )
    save_snapshot(calculation, report)


def append_key_client_profit(
    calculation: Calculation,
    client: str,
    profit: float,
) -> None:
    report = load_snapshot(calculation)
    section = report.setdefault("key_clients_profit", {})
    items = section.setdefault("items", [])
    filled_items = [item for item in items if _key_client_item_filled(item)]
    bonus = _key_client_bonus(section, profit)
    filled_items.append({"client": client.strip(), "profit": profit, "bonus": bonus})
    section["items"] = filled_items
    section["bonus"] = round_half_up(sum(float(item.get("bonus") or 0) for item in filled_items))
    save_snapshot(calculation, report)


def update_key_client_profit(
    calculation: Calculation,
    old_client: str,
    old_profit: float,
    new_client: str,
    new_profit: float,
) -> None:
    report = load_snapshot(calculation)
    section = report.setdefault("key_clients_profit", {})
    items = section.setdefault("items", [])
    item = _find_key_client_item(items, old_client, old_profit)
    if item is None:
        filled_items = [candidate for candidate in items if _key_client_item_filled(candidate)]
        item = {}
        filled_items.append(item)
        section["items"] = filled_items
    item.update({
        "client": new_client.strip(),
        "profit": new_profit,
        "bonus": _key_client_bonus(section, new_profit),
    })
    section["bonus"] = round_half_up(sum(
        float(candidate.get("bonus") or 0)
        for candidate in section["items"]
        if _key_client_item_filled(candidate)
    ))
    save_snapshot(calculation, report)


def remove_key_client_profit(
    calculation: Calculation,
    client: str,
    profit: float,
) -> None:
    report = load_snapshot(calculation)
    section = report.setdefault("key_clients_profit", {})
    items = section.setdefault("items", [])
    item = _find_key_client_item(items, client, profit)
    if item is not None:
        items.remove(item)
    filled_items = [candidate for candidate in items if _key_client_item_filled(candidate)]
    section["items"] = filled_items or [{"client": "", "profit": None, "bonus": None}]
    section["bonus"] = round_half_up(sum(float(candidate.get("bonus") or 0) for candidate in filled_items))
    save_snapshot(calculation, report)


def _key_client_bonus(section: dict, profit: float) -> float:
    rate = float(section.get("bonus_percent") or 0)
    return round_half_up(float(profit) * rate)


def _key_client_item_filled(item: dict) -> bool:
    return bool(str(item.get("client") or "").strip()) or item.get("profit") is not None


def _find_key_client_item(items: list[dict], client: str, profit: float) -> dict | None:
    for item in items:
        if _text_matches(item.get("client"), client) and _amount_matches(item.get("profit"), profit):
            return item
    return None


def update_adjustment(
    calculation: Calculation,
    old_section_code: str,
    old_adjustment_type: str,
    old_amount: float,
    old_comment: str,
    new_section_code: str,
    new_adjustment_type: str,
    new_amount: float,
    new_comment: str,
) -> None:
    if old_section_code == "debt" and new_section_code == "debt":
        refresh_calculated_values(calculation)
        report = load_snapshot(calculation)
        item = _find_adjustment(report.get("manual_adjustments", []), "debt", "debt_amount", old_amount, old_comment)
        if item is not None:
            item.update(amount=new_amount, comment=new_comment)
        save_snapshot(calculation, report)
        return
    report = load_snapshot(calculation)
    adjustments = report.setdefault("manual_adjustments", [])
    adjustment = _find_adjustment(
        adjustments,
        old_section_code,
        old_adjustment_type,
        old_amount,
        old_comment,
    )
    if adjustment is not None:
        adjustment["section_code"] = new_section_code
        adjustment["adjustment_type"] = new_adjustment_type
        adjustment["amount"] = new_amount
        adjustment["comment"] = new_comment

    update_additional_payment(
        calculation,
        _adjustment_description(old_comment),
        old_amount,
        _adjustment_description(new_comment),
        new_amount,
    )
    if adjustment is not None:
        report = load_snapshot(calculation)
        adjustments = report.setdefault("manual_adjustments", [])
        adjustment = _find_adjustment(
            adjustments,
            old_section_code,
            old_adjustment_type,
            old_amount,
            old_comment,
        )
        if adjustment is not None:
            adjustment["section_code"] = new_section_code
            adjustment["adjustment_type"] = new_adjustment_type
            adjustment["amount"] = new_amount
            adjustment["comment"] = new_comment
        save_snapshot(calculation, report)


def remove_adjustment(
    calculation: Calculation,
    section_code: str,
    adjustment_type: str,
    amount: float,
    comment: str,
) -> None:
    if section_code == "debt":
        refresh_calculated_values(calculation)
        report = load_snapshot(calculation)
        items = report.get("manual_adjustments", [])
        item = _find_adjustment(items, "debt", "debt_amount", amount, comment)
        if item is not None:
            items.remove(item)
        save_snapshot(calculation, report)
        return
    report = load_snapshot(calculation)
    adjustments = report.setdefault("manual_adjustments", [])
    adjustment = _find_adjustment(
        adjustments,
        section_code,
        adjustment_type,
        amount,
        comment,
    )
    if adjustment is not None:
        adjustments.remove(adjustment)
    items = report.setdefault("additional_payments", {}).setdefault("items", [])
    payment_item = _find_payment_item(items, _adjustment_description(comment), amount)
    if payment_item is not None:
        items.remove(payment_item)
    save_snapshot(calculation, report)


def _adjustment_description(comment: str) -> str:
    return str(comment or "").strip() or "Корректировка"


def _find_adjustment(
    adjustments: list[dict],
    section_code: str,
    adjustment_type: str,
    amount: float,
    comment: str,
) -> dict | None:
    for adjustment in adjustments:
        if (
            _text_matches(adjustment.get("section_code"), section_code)
            and _text_matches(adjustment.get("adjustment_type"), adjustment_type)
            and _amount_matches(adjustment.get("amount"), amount)
            and _text_matches(adjustment.get("comment"), comment)
        ):
            return adjustment
    return None


def generate_pdf_for_calculation(db: Session, calculation: Calculation) -> Path:
    report = load_snapshot(calculation)
    period = calculation.period
    output_dir = period_storage_dir(GENERATED_DIR, period)
    output_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = output_dir / f"{report_stem(report['employee'], period.year, period.month)}.pdf"

    if report.get("report_type") == "chief":
        generate_chief_pdf(pdf_path, report, period.year, period.month)
    elif report.get("report_type") == "manager":
        generate_pdf(
            pdf_path,
            report["employee"],
            report["profit"],
            report["brand"],
            report["debt"],
            report["cycle"],
            report["communications"],
            report["timesheet"],
            report["additional_payments"],
            period.year,
            period.month,
        )
    else:
        raise ValueError(f"Неизвестный тип расчета: {report.get('report_type')}")

    calculation.pdf_path = stored_service_data_path(pdf_path)
    db.flush()
    return pdf_path


def _additional_total(report: dict) -> float:
    return round_half_up(sum(
        float(item.get("amount") or 0)
        for item in report.get("additional_payments", {}).get("items", [])
    ))


def _recalculate_totals(report: dict) -> None:
    _recalculate_debt_adjustments(report)
    additional_payments = report.setdefault("additional_payments", {})
    additional_payments["total"] = _additional_total(report)

    if report.get("report_type") == "chief":
        _recalculate_chief_totals(report)
    else:
        _recalculate_manager_totals(report)


def _recalculate_debt_adjustments(report: dict) -> None:
    adjustments = [item for item in report.get("manual_adjustments", []) if item.get("section_code") == "debt"]
    debt = report.setdefault("debt", {})
    if not adjustments and "original_total" not in debt:
        return
    debt.setdefault("original_total", debt["total"])
    payments = report.setdefault("additional_payments", {}).setdefault("items", [])
    for item in adjustments:
        if item.get("adjustment_type") != "debt_amount":
            payment = _find_payment_item(payments, _adjustment_description(item.get("comment")), item["amount"])
            if payment is not None:
                payments.remove(payment)
            item["adjustment_type"] = "debt_amount"
    debt["adjustment_total"] = round_half_up(sum(float(item["amount"]) for item in adjustments))
    debt["corrections"] = [{"amount": item["amount"], "comment": item.get("comment", "")} for item in adjustments]
    debt["total"] = round_half_up(float(debt["original_total"]) + debt["adjustment_total"])
    is_chief = report.get("report_type") == "chief"
    rate = debt.get("responsibility_percent", CHIEF_OVERDUE_DEBT_PERCENT) if is_chief else OVERDUE_DEBT_PERCENT
    responsibility = debt["total"] * rate
    debt["responsibility"] = round(responsibility, 2) if is_chief else responsibility
    sales = float(report.get("profit", {}).get("sales") or 0)
    debt["ratio"] = debt["total"] / sales * 100 if sales > 0 else 0


def _recalculate_manager_totals(report: dict) -> None:
    total_bonus = round_half_up(
        float(report["profit"]["bonus"])
        + float(report["brand"]["zic_bonus_total"])
        + float(report["brand"].get("lukoil_bonus") or 0)
        + float(report["brand"]["other_bonus_total"])
        + float(report["cycle"]["bonus"])
        + float(report["additional_payments"]["total"])
        - float(report["debt"]["responsibility"])
    )
    report["total_bonus"] = total_bonus
    report["salary_total"] = round_half_up(total_bonus + float(report["timesheet"]["salary"]))


def _recalculate_chief_totals(report: dict) -> None:
    total_bonus = round_half_up(
        float(report["profit"]["kpi"]["bonus"])
        + float(report["cycle"]["bonus"])
        + float(report["zic"]["bonus"])
        + float(report["other"]["bonus"])
        + float(report["lukoil"]["bonus"])
        + float(report["key_clients_profit"]["bonus"])
        + float(report["additional_payments"]["total"])
        - float(report["debt"]["responsibility"])
    )
    report["total_bonus"] = total_bonus
    report["salary_total"] = round_half_up(total_bonus + float(report["timesheet"]["salary"]))
