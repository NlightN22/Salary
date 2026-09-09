from datetime import datetime
from calendar import monthrange

import pandas as pd

from directions.b2b.config import CYCLE_BONUS_BASE
from services.rounding import round_half_up


class CycleParser:

    PLAN_STAGES = {
        "отгрузка и доставка",
    }

    FACT_STAGES = {
        "выявление потребности",
        "коммерческое предложение",
        "опытно-производственные испытания",
        "первичный контакт",
    }

    def __init__(self, df: pd.DataFrame):

        self.df = df

        self.stage_col = None
        self.first_contact_col = None
        self.last_change_col = None

        self._detect_columns()

    # ==================================================
    # Поиск колонок
    # ==================================================

    def _detect_columns(self):

        columns = [
            str(col).strip().lower()
            for col in self.df.columns
        ]

        for idx, col in enumerate(columns):

            if "дата первичного контакта" in col:
                self.first_contact_col = idx

            elif "дата последнего изменения" in col:
                self.last_change_col = idx

            elif (
                "сделки" in col
                or "процессы" in col
                or "события" in col
            ):
                self.stage_col = idx

        if self.stage_col is None:
            self.stage_col = 0

        if self.first_contact_col is None:
            raise ValueError(
                "Не найдена колонка "
                "'Дата первичного контакта'"
            )

        if self.last_change_col is None:
            raise ValueError(
                "Не найдена колонка "
                "'Дата последнего изменения'"
            )

    # ==================================================
    # Преобразование даты
    # ==================================================

    def _parse_date(self, value):

        if pd.isna(value):
            return None

        if isinstance(value, datetime):
            return value

        value = str(value).strip()

        if not value:
            return None

        formats = [
            "%d.%m.%Y",
            "%d.%m.%Y %H:%M:%S",
            "%Y-%m-%d",
            "%Y-%m-%d %H:%M:%S",
        ]

        for fmt in formats:

            try:
                return datetime.strptime(
                    value,
                    fmt
                )

            except Exception:
                pass

        try:
            return pd.to_datetime(
                value,
                dayfirst=True,
                errors="coerce"
            )

        except Exception:
            return None

    # ==================================================
    # Получить данные сотрудника
    # ==================================================

    def get_cycle_data(
        self,
        employee,
        year,
        month,
    ):

        surname = (
            employee.split()[0]
            .strip()
            .lower()
        )

        name = (
            employee.split()[1]
            .strip()
            .lower()
        )

        last_day = monthrange(
            year,
            month
        )[1]

        calc_date = datetime(
            year,
            month,
            last_day
        )

        employee_found = False
        current_stage = None

        plan_days = []
        fact_days = []

        for _, row in self.df.iterrows():

            value = row.iloc[self.stage_col]

            if pd.isna(value):
                continue

            value = str(value).strip()

            lower_value = value.lower()

            # ==========================================
            # Нашли сотрудника
            # ==========================================

            if (
                lower_value.startswith(
                    ">> группа:"
                )
                and surname in lower_value
                and name in lower_value
            ):

                employee_found = True
                current_stage = None

                continue

            if not employee_found:
                continue

            # ==========================================
            # Новый раздел
            # ==========================================

            if (
                lower_value.startswith(
                    ">> группа:"
                )
            ):

                stage_name = (
                    lower_value
                    .replace(
                        ">> группа:",
                        ""
                    )
                    .strip()
                )

                if "(" in stage_name:

                    stage_name = (
                        stage_name
                        .split("(")[0]
                        .strip()
                    )

                current_stage = stage_name

                continue

            # ==========================================
            # Обрабатываем только нужные стадии
            # ==========================================

            if (
                current_stage
                not in self.PLAN_STAGES
                and current_stage
                not in self.FACT_STAGES
            ):
                continue

            first_contact = self._parse_date(
                row.iloc[
                    self.first_contact_col
                ]
            )

            if first_contact is None:
                continue

            # ==========================================
            # План
            # ==========================================

            if (
                current_stage
                in self.PLAN_STAGES
            ):

                last_change = (
                    self._parse_date(
                        row.iloc[
                            self.last_change_col
                        ]
                    )
                )

                if last_change is None:
                    continue

                days = (
                    last_change
                    - first_contact
                ).days

                if days >= 0:
                    plan_days.append(days)

            # ==========================================
            # Факт
            # ==========================================

            else:

                days = (
                    calc_date
                    - first_contact
                ).days

                if days >= 0:
                    fact_days.append(days)

        # ==============================================
        # Средние значения
        # ==============================================

        plan = (
            sum(plan_days)
            / len(plan_days)
            if plan_days
            else 0
        )

        fact = (
            sum(fact_days)
            / len(fact_days)
            if fact_days
            else 0
        )

        # В рабочих Excel-расчётках исторический план фиксируется до сотых,
        # а текущий средний цикл CRM — до десятых (например, 641,5).
        # Расчёт бонуса должен использовать именно эти зафиксированные значения.
        plan = round_half_up(plan, 2)
        fact = round_half_up(fact, 1)

        # ==============================================
        # Бонус
        # ==============================================

        if fact > 0:

            ratio = (
                plan / fact
            )

            bonus = round_half_up(
                ratio
                * CYCLE_BONUS_BASE
            )

        else:

            ratio = 0
            bonus = 0

        return {

            "plan": plan,

            "fact": fact,

            "ratio": round(
                ratio,
                4
            ),

            "bonus": bonus,

            # диагностика

            "plan_count": len(
                plan_days
            ),

            "fact_count": len(
                fact_days
            ),

            "plan_days_sum": sum(
                plan_days
            ),

            "fact_days_sum": sum(
                fact_days
            ),
        }
