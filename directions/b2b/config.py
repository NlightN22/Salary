PROFIT_BONUS_PERCENT = 0.05 # Размер премии от дохода в %

# Идентификатор и имя отдельного каталога направления.
DEPARTMENT_CODE = "b2b"
DEPARTMENT_NAME = "B2B-направление"

ZIC_BONUS_BASE = 40000 # базовый размер премии за ZIC
OTHER_BONUS_BASE = 30000 # базовый размер премии за другие бренды
OTHER_KPI_WEIGHTS = {   # распределение весов по брендам
    "В2В Полярная Звезда": 22.5,
    "В2В VegaOil": 50.0,
    "B2B GSK": 27.5,
}

OVERDUE_DEBT_PERCENT = 0.01 # размер ответственности за ПДЗ %
OVERDUE_DEBT_THRESHOLD = 100000 # порог для детализации ПДЗ в расчетке

CYCLE_BONUS_BASE = 20000 # базовый размер премии за циклы сделок

HOUR_RATE = 322.59 # стоимость часа работы менеджера

# Руководитель B2B-направления
CHIEF_EMPLOYEE = "Погорельцев Роман Олегович"

# KPI руководителя
CHIEF_PROFIT_BONUS_BASE = 10000
CHIEF_PROFITABILITY_BASE_PERCENT = 18.03
CHIEF_INCOME_WEIGHT = 0.6
CHIEF_PROFITABILITY_WEIGHT = 0.4
CHIEF_CYCLE_BONUS_BASE = 50000
CHIEF_ZIC_BONUS_BASE = 100000
CHIEF_LUKOIL_BONUS_COEFFICIENT = 0.25
CHIEF_KEY_CLIENT_PROFIT_BONUS_PERCENT = 0.10  # коэффициент 0.10 = 10% от прибыли
CHIEF_OTHER_BONUS_BASE = 70000
CHIEF_SPECIAL_PRODUCT_WEIGHTS = {
    "В2В Полярная Звезда": 27.5,
    "В2В VegaOil": 20.0,
    "B2B GSK": 52.5,
}
CHIEF_HOUR_RATE = 322.59
CHIEF_DEBT_THRESHOLD = 100000
CHIEF_OVERDUE_DEBT_PERCENT = 0.01
