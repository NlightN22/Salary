"""Direction totals and salary calculation for the configured B2B chief."""

from directions.b2b.config import (
    CHIEF_CYCLE_BONUS_BASE,
    CHIEF_DEBT_THRESHOLD,
    CHIEF_EMPLOYEE,
    CHIEF_HOUR_RATE,
    CHIEF_INCOME_WEIGHT,
    CHIEF_KEY_CLIENT_PROFIT_BONUS_PERCENT,
    CHIEF_OTHER_BONUS_BASE,
    CHIEF_OVERDUE_DEBT_PERCENT,
    CHIEF_PROFIT_BONUS_BASE,
    CHIEF_PROFITABILITY_BASE_PERCENT,
    CHIEF_PROFITABILITY_WEIGHT,
    CHIEF_SPECIAL_PRODUCT_WEIGHTS,
    CHIEF_ZIC_BONUS_BASE,
)
from services.rounding import round_half_up


def _scaled_bonus(percent, base):
    return round_half_up(float(percent) / 100 * base)


def calculate_chief(context, manager_reports):
    profit = context["profit"].get_total()
    profit_kpi = context["brand"].get_kpi_row(CHIEF_EMPLOYEE, "B2B Прибыль")
    income_weighted_percent = profit_kpi["percent"] * CHIEF_INCOME_WEIGHT
    profitability_percent = (
        profit["profitability"] / CHIEF_PROFITABILITY_BASE_PERCENT * 100
        if CHIEF_PROFITABILITY_BASE_PERCENT else 0
    )
    profitability_weighted_percent = profitability_percent * CHIEF_PROFITABILITY_WEIGHT
    total_percent = income_weighted_percent + profitability_weighted_percent
    profit_kpi["bonus_base"] = CHIEF_PROFIT_BONUS_BASE
    profit_kpi.update({
        "income_weight": CHIEF_INCOME_WEIGHT,
        "income_weighted_percent": round(income_weighted_percent, 4),
        "profitability_base_percent": CHIEF_PROFITABILITY_BASE_PERCENT,
        "profitability_percent": round(profitability_percent, 4),
        "profitability_weight": CHIEF_PROFITABILITY_WEIGHT,
        "profitability_weighted_percent": round(profitability_weighted_percent, 4),
        "total_percent": round(total_percent, 4),
        "bonus": _scaled_bonus(total_percent, CHIEF_PROFIT_BONUS_BASE),
    })

    cycle_count_plan = sum(item["cycle"]["plan_count"] for item in manager_reports)
    cycle_count_fact = sum(item["cycle"]["fact_count"] for item in manager_reports)
    plan = sum(item["cycle"]["plan_days_sum"] for item in manager_reports) / cycle_count_plan if cycle_count_plan else 0
    fact = sum(item["cycle"]["fact_days_sum"] for item in manager_reports) / cycle_count_fact if cycle_count_fact else 0
    plan = round_half_up(plan)
    fact = round_half_up(fact)
    cycle_ratio = plan / fact if fact else 0
    cycle = {
        "plan": plan, "fact": fact, "ratio": round(cycle_ratio, 4),
        "bonus_base": CHIEF_CYCLE_BONUS_BASE,
        "bonus": round_half_up(cycle_ratio * CHIEF_CYCLE_BONUS_BASE),
        "plan_count": cycle_count_plan, "fact_count": cycle_count_fact,
    }

    zic = context["brand"].get_kpi_row(CHIEF_EMPLOYEE, "ZIC")
    zic["bonus_base"] = CHIEF_ZIC_BONUS_BASE
    zic["bonus"] = _scaled_bonus(zic["percent"], CHIEF_ZIC_BONUS_BASE)

    lukoil = {
        "calculation_enabled": False,
        "manager_items": [],
        "manager_bonus_total": 0.0,
        "coefficient": None,
        "bonus": 0.0,
    }

    key_clients_profit = {
        "bonus_percent": CHIEF_KEY_CLIENT_PROFIT_BONUS_PERCENT,
        "items": [{"client": "", "profit": None, "bonus": None}],
        "bonus": 0.0,
    }

    raw_other = []
    for item in context["brand"].get_employee_kpi(CHIEF_EMPLOYEE)["other"]:
        weight = CHIEF_SPECIAL_PRODUCT_WEIGHTS.get(item["brand"], 0)
        if weight <= 0:
            continue
        raw_other.append({
            **item,
            "weight": weight,
            "weighted_percent": item["percent"] * weight / 100,
        })
    total_percent = sum(item.get("weighted_percent", 0) for item in raw_other)
    raw_ratio = total_percent / 100
    if raw_ratio > 1.2:
        ratio = 1.2
    elif raw_ratio < 0.5:
        ratio = raw_ratio * 0.8
    else:
        ratio = raw_ratio
    other = {
        "items": raw_other, "percent": round(total_percent, 2),
        "calculation_percent": round(ratio * 100, 2),
        "bonus_base": CHIEF_OTHER_BONUS_BASE,
        "bonus": round_half_up(CHIEF_OTHER_BONUS_BASE * ratio),
    }

    debt = context["debt"].get_direction_data(CHIEF_DEBT_THRESHOLD)
    debt["threshold"] = CHIEF_DEBT_THRESHOLD
    debt["responsibility_percent"] = CHIEF_OVERDUE_DEBT_PERCENT
    debt["responsibility"] = round(debt["total"] * CHIEF_OVERDUE_DEBT_PERCENT, 2)
    timesheet = context["timesheet"].get_data(CHIEF_EMPLOYEE, CHIEF_HOUR_RATE)
    additional_payments = {
        "items": [
            {"description": "", "amount": None},
            {"description": "", "amount": None},
        ],
        "total": 0.0,
    }

    total_bonus = round_half_up(
        profit_kpi["bonus"] + cycle["bonus"] + zic["bonus"] + other["bonus"]
        + lukoil["bonus"] + key_clients_profit["bonus"]
        + additional_payments["total"] - debt["responsibility"]
    )
    return {
        "report_type": "chief", "employee": CHIEF_EMPLOYEE,
        "profit": {**profit, "kpi": profit_kpi},
        "cycle": cycle, "zic": zic, "other": other, "debt": debt,
        "lukoil": lukoil,
        "key_clients_profit": key_clients_profit,
        "additional_payments": additional_payments,
        "timesheet": timesheet, "total_bonus": total_bonus,
        "salary_total": round_half_up(total_bonus + timesheet["salary"]),
    }
