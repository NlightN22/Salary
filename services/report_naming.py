MONTHS = {
    1: "январь", 2: "февраль", 3: "март", 4: "апрель",
    5: "май", 6: "июнь", 7: "июль", 8: "август",
    9: "сентябрь", 10: "октябрь", 11: "ноябрь", 12: "декабрь",
}


def report_stem(employee, year, month):
    full_name = "_".join(str(employee).split())
    safe_name = full_name.replace("/", "_").replace("\\", "_").replace(":", "_")
    return f"{safe_name}_{MONTHS[month]}_{year}"
