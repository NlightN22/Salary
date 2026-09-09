import pandas as pd

from directions.b2b.config import PROFIT_BONUS_PERCENT
from services.rounding import round_half_up


class ProfitParser:

    def __init__(self, df: pd.DataFrame):

        self.df = df

        self.manager_col = None
        self.sales_col = None
        self.income_col = None
        self.profitability_col = None

        self._detect_columns()

    # ==================================================
    # Поиск колонок
    # ==================================================

    def _detect_columns(self):

        for _, row in self.df.iterrows():

            for idx, value in enumerate(row):

                if pd.isna(value):
                    continue

                value = str(value).strip().lower()

                if "менеджер" in value:
                    self.manager_col = idx

                elif "сумма продажи" in value:
                    self.sales_col = idx

                elif "доход текущий" in value:
                    self.income_col = idx

                elif "рентабельность текущая" in value:
                    self.profitability_col = idx

            if (
                self.manager_col is not None
                and self.sales_col is not None
                and self.income_col is not None
                and self.profitability_col is not None
            ):
                return

        raise ValueError(
            "Не удалось определить колонки Profit"
        )

    # ==================================================
    # Строка сотрудника?
    # ==================================================

    def _is_employee_row(self, row):

        try:

            name = row.iloc[self.manager_col]

            if pd.isna(name):
                return False

            name = str(name).strip()

            if not name:
                return False

            words = name.split()

            if len(words) < 3:
                return False

            sales = row.iloc[self.sales_col]

            if pd.isna(sales):
                return False

            float(sales)

            return True

        except Exception:

            return False

    # ==================================================
    # Список сотрудников
    # ==================================================

    def get_employees(self):

        employees = set()

        for _, row in self.df.iterrows():

            if self._is_employee_row(row):

                employees.add(
                    str(
                        row.iloc[self.manager_col]
                    ).strip()
                )

        return employees

    # ==================================================
    # Получить данные сотрудника
    # ==================================================

    def get_income(self, employee):

        employee = str(employee).strip()

        for _, row in self.df.iterrows():

            if not self._is_employee_row(row):
                continue

            name = str(
                row.iloc[self.manager_col]
            ).strip()

            if name != employee:
                continue

            # _is_employee_row has already verified that sales is numeric.
            sales = float(row.iloc[self.sales_col])

            try:
                income = float(
                    row.iloc[self.income_col]
                )
            except Exception:
                income = 0

            try:
                profitability = float(
                    row.iloc[
                        self.profitability_col
                    ]
                )
            except Exception:
                profitability = 0

            sales = round_half_up(sales)
            income = round_half_up(income)
            bonus = round_half_up(income * PROFIT_BONUS_PERCENT)

            return {
                "sales": sales,
                "income": income,
                "profitability": profitability,
                "bonus": bonus,
            }

        return {
            "sales": 0,
            "income": 0,
            "profitability": 0,
            "bonus": 0,
        }

    def get_total(self):
        """Return the direction-wide values from the report's 'Итого' row."""
        for _, row in self.df.iterrows():
            value = row.iloc[self.manager_col]
            if pd.isna(value) or str(value).strip().lower() != "итого":
                continue

            def number(column):
                try:
                    return round_half_up(float(row.iloc[column]))
                except (TypeError, ValueError):
                    return 0.0

            return {
                "sales": number(self.sales_col),
                "income": number(self.income_col),
                "profitability": number(self.profitability_col),
            }

        raise ValueError("В отчете Profit не найдена строка 'Итого'")

    # ==================================================
    # Отладка
    # ==================================================

    def print_columns(self):

        print(
            f"Менеджер: {self.manager_col}"
        )

        print(
            f"Продажи: {self.sales_col}"
        )

        print(
            f"Доход: {self.income_col}"
        )

        print(
            f"Рентабельность: "
            f"{self.profitability_col}"
        )
