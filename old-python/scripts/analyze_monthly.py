import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.rules import get_item_category
from database.connection import get_clean_receipts

# Получаем чистые чеки за период с марта по июнь
receipts = get_clean_receipts("2026-03-01T00:00:00", "2026-06-30T23:59:59")

# Группировка расходов по месяцам и категориям
monthly_expenses = {3: {}, 4: {}, 5: {}, 6: {}}

for _rkey, r in receipts.items():
    month = r["date"].month
    if month not in monthly_expenses:
        continue

    for item in r["items"]:
        name = item["name"]
        val = item["sum"]

        if name in ["Платеж", "Предоплата", "Аванс"]:
            continue

        matched_cat = get_item_category(name, r["owner"])
        monthly_expenses[month][matched_cat] = monthly_expenses[month].get(matched_cat, 0.0) + val

month_names = {3: "Март", 4: "Апрель", 5: "Май", 6: "Июнь"}

for month, data in monthly_expenses.items():
    total = sum(data.values())
    print(f"=== {month_names[month]} 2026 ===")
    print(f"Всего потрачено: {total:.2f} ₽")
    for cat, val in sorted(data.items(), key=lambda x: x[1], reverse=True):
        share = (val / total) * 100 if total > 0 else 0
        print(f"  {cat}: {val:.2f} ₽ ({share:.1f}%)")
    print()
