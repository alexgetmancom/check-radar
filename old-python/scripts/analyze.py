import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.rules import get_item_category
from database.connection import get_clean_receipts

# Получаем чистые чеки за период с марта по июнь
receipts = get_clean_receipts("2026-03-01T00:00:00", "2026-06-30T23:59:59")

grouped_expenses = {}

for _rkey, r in receipts.items():
    for item in r["items"]:
        name = item["name"]
        val = item["sum"]

        # Исключаем чисто авансовые позиции 'Платеж'/'Предоплата' в доставках
        if name in ["Платеж", "Предоплата", "Аванс"]:
            continue

        matched_cat = get_item_category(name, r["owner"])
        grouped_expenses[matched_cat] = grouped_expenses.get(matched_cat, 0.0) + val

# Выводим суммы
total_spent = sum(grouped_expenses.values())
print(f"=== Всего очищено расходов (март-июнь): {total_spent:.2f} ₽ ===")
for cat, val in sorted(grouped_expenses.items(), key=lambda x: x[1], reverse=True):
    share = (val / total_spent) * 100 if total_spent > 0 else 0
    print(f"{cat}: {val:.2f} ₽ ({share:.1f}%)")
