import pandas as pd

from directions.b2b.config import HOUR_RATE


class TimesheetParser:

    def __init__(self, df):

        self.df = df

    # ==========================================
    # Получить данные сотрудника
    # ==========================================

    def get_data(self, employee, hour_rate=HOUR_RATE):

        parts = employee.split()

        if len(parts) < 2:

            return {
                "hours": 0,
                "salary": 0,
            }

        surname = parts[0].lower()

        first_letter = (
            parts[1][0].lower()
        )

        for _, row in self.df.iterrows():

            try:

                name = str(
                    row.iloc[0]
                ).strip()

                normalized_name = name.lower()
                if surname not in normalized_name:
                    continue

                name_parts = normalized_name.replace(".", " ").split()
                reported_initial = name_parts[1][0] if len(name_parts) > 1 else ""
                if first_letter != reported_initial:
                    continue

                hours_text = str(
                    row.iloc[1]
                )

                hours_text = (
                    hours_text
                    .split("\n")[0]
                    .replace(",", ".")
                    .strip()
                )

                hours = float(
                    hours_text
                )

                return {

                    "hours": round(
                        hours,
                        2
                    ),

                    "salary": round(
                        hours
                        * hour_rate,
                        2
                    ),
                }

            except Exception:

                continue

        return {

            "hours": 0,

            "salary": 0,
        }
