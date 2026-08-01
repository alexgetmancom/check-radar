from datetime import datetime
from typing import Any, Optional

from config.rules import get_food_subcategory, get_item_category, simplify_store_name


def format_receipt_html(
    receipt: dict[str, Any], fd: Optional[dict[str, Any]], owner_phone: Optional[str] = None
) -> str:
    owner = simplify_store_name(receipt.get("kktOwner", "Неизвестный магазин"))
    total_sum = float(receipt.get("totalSum", 0))
    dt_str = receipt.get("createdDate")
    if dt_str:
        dt = datetime.fromisoformat(dt_str).strftime("%d.%m.%Y %H:%M")
    else:
        dt = "Неизвестная дата"

    html = f"<h1>🛒 {owner}</h1>"
    if owner_phone:
        names = {"79639629392": "Лёша", "79013652064": "Маша"}
        name = names.get(owner_phone, owner_phone)
        html += f"<p>💳 <b>Оплатил(а):</b> {name}</p>\n"
    html += f"<p>📅 <i>{dt}</i> | 💰 <b>Итого: {total_sum:.2f} ₽</b></p>\n"

    subcategorized_items: dict[str, dict[str, dict[str, float]]] = {}
    has_items = False

    if fd and "items" in fd:
        for item in fd["items"]:
            name = item.get("name", "Товар")
            if name in ["Платеж", "Предоплата", "Аванс"]:
                continue
            qty = item.get("quantity", 1.0)
            price = item.get("price", 0.0)
            val = item.get("sum", 0.0)

            if val <= 0.01 or price <= 0.01:
                continue

            has_items = True
            main_cat = get_item_category(name, receipt.get("kktOwner", ""))

            if main_cat == "Продукты питания и напитки":
                subcat = get_food_subcategory(name, receipt.get("kktOwner", ""))
                if not subcat:
                    subcat = "📦 Прочие продукты"
            else:
                icon_map = {
                    "Бытовая техника и электроника": "🔌 Бытовая техника",
                    "Товары для питомцев (корма)": "🐈 Товары для питомцев",
                    "Одежда и обувь": "👕 Одежда и обувь",
                    "Хостинг, серверы и облака": "☁️ Хостинг и облака",
                    "Связь и интернет-провайдеры": "🌐 Связь и интернет",
                    "Транспорт (Такси)": "🚕 Такси",
                    "Кафе и рестораны / Готовая еда": "🍕 Кафе и рестораны",
                    "Доставка и сервисные сборы": "🛵 Доставка и сборы",
                    "Гигиена и бытовая химия": "🧼 Гигиена и химия",
                    "Упаковка / Пакеты": "🛍️ Пакеты",
                    "Подписки и лояльность": "🎟️ Подписки",
                    "Объявления и реклама": "📣 Объявления",
                }
                subcat = icon_map.get(main_cat, f"📦 {main_cat}")

            # Оптимизация вложенных словарей через setdefault (Стандарт 2026)
            sub_dict = subcategorized_items.setdefault(subcat, {})
            item_entry = sub_dict.setdefault(name, {"price": price, "qty": 0.0, "sum": 0.0})
            item_entry["qty"] += qty
            item_entry["sum"] += val

    if has_items:
        sorted_subcats = sorted(subcategorized_items.keys())
        for subcat in sorted_subcats:
            html += f"<h3>{subcat}:</h3>"
            html += "<table bordered striped>"
            html += "<tr><th>Товар</th><th>Кол-во</th><th>Сумма</th></tr>"

            for name, data in subcategorized_items[subcat].items():
                qty = data["qty"]
                val = data["sum"]
                price = data["price"]
                unit_price_str = f" (<i>{price:.2f} ₽/шт</i>)" if qty > 1.0 else ""
                html += f"<tr><td>{name}</td><td>{qty:.1f} шт</td><td><b>{val:.2f} ₽</b>{unit_price_str}</td></tr>"
            html += "</table>\n"
    else:
        html += "<p>💳 <b>Предоплата заказа / Авансовый платёж</b></p>\n"

    return html


def format_weekly_report(
    start_this: datetime,
    end_this: datetime,
    start_last: datetime,
    end_last: datetime,
    cats_this: dict[str, float],
    cats_last: dict[str, float],
    total_this: float,
    total_last: float,
    items_this: list[tuple[str, str, float]],
) -> str:
    diff = total_this - total_last
    diff_pct = (diff / total_last * 100) if total_last > 0 else 0.0

    html = "<h1>📊 Финансовый отчет за неделю</h1>"
    html += f"<p><i>Сравнение: {start_this.strftime('%d.%m')} - {end_this.strftime('%d.%m')} vs {start_last.strftime('%d.%m')} - {end_last.strftime('%d.%m')}</i></p>\n"

    sign = "+" if diff > 0 else ""
    html += f"<p>💰 <b>Траты на этой неделе:</b> {total_this:.2f} ₽<br>\n"
    html += (
        f"📊 <b>Изменение:</b> {sign}{diff:.2f} ₽ (<i>{sign}{diff_pct:.1f}%</i>) vs прошлые {total_last:.0f} ₽</p>\n"
    )

    income_this = cats_this.get("Доходы", 0.0)
    income_last = cats_last.get("Доходы", 0.0)
    if income_this > 0 or income_last > 0:
        income_diff = income_this - income_last
        income_sign = "+" if income_diff > 0 else ""
        html += f"<p>📈 <b>Доходы на этой неделе:</b> {income_this:.2f} ₽ (<i>{income_sign}{income_diff:.2f} ₽</i> vs {income_last:.0f} ₽)</p>\n"

    html += "<h2>📊 Распределение по категориям:</h2>"
    html += "<table bordered striped>"
    html += "<tr><th>Категория</th><th>Эта неделя</th><th>Было</th><th>Дельта</th></tr>"

    all_cats = sorted(list((set(cats_this.keys()) | set(cats_last.keys())) - {"Доходы"}))
    for cat in all_cats:
        v_this = cats_this.get(cat, 0.0)
        v_last = cats_last.get(cat, 0.0)
        v_diff = v_this - v_last
        v_sign = "+" if v_diff > 0 else ""

        if v_this == 0 and v_last == 0:
            continue

        html += f"<tr><td>{cat}</td><td>{v_this:.0f} ₽</td><td>{v_last:.0f} ₽</td><td><b>{v_sign}{v_diff:.0f} ₽</b></td></tr>"
    html += "</table>\n"

    # Топ-5 крупных покупок
    top_items = sorted(items_this, key=lambda x: x[2], reverse=True)[:5]
    if top_items:
        html += "<h2>🔝 Топ-5 трат недели:</h2>"
        html += "<ul>"
        for store, name, sum_val in top_items:
            store_clean = simplify_store_name(store)
            html += f"<li><b>{sum_val:.2f} ₽</b> — {store_clean}: {name[:30]}...</li>"
        html += "</ul>"

    return html


def format_monthly_stats(
    total: float, cats: dict[str, float], total_lesha: float = 0.0, total_masha: float = 0.0
) -> str:
    html = "<h1>📊 Статистика расходов за месяц</h1>"
    html += f"<p>💰 <b>Всего трат:</b> {total:.2f} ₽</p>"

    income = cats.get("Доходы", 0.0)
    if income > 0:
        html += f"<p>📈 <b>Всего доходов:</b> {income:.2f} ₽</p>"

    if total_lesha > 0 or total_masha > 0:
        html += f"<p>🧔 <b>Лёша:</b> {total_lesha:.2f} ₽ | 👩 <b>Маша:</b> {total_masha:.2f} ₽</p>"

    html += "<table bordered striped>"
    html += "<tr><th>Категория</th><th>Сумма</th><th>Доля</th></tr>"

    sorted_cats = sorted([(cat, val) for cat, val in cats.items() if cat != "Доходы"], key=lambda x: x[1], reverse=True)
    for cat, val in sorted_cats:
        share = (val / total * 100) if total > 0 else 0.0
        html += f"<tr><td>{cat}</td><td><b>{val:.2f} ₽</b></td><td><i>{share:.1f}%</i></td></tr>"
    html += "</table>"

    return html


def format_food_stats(total_food: float, food_expenses: dict[str, float]) -> str:
    html = "<h1>🛒 Расходы на еду и продукты</h1>"
    html += f"<p>💰 <b>Итого продукты:</b> {total_food:.2f} ₽</p>"

    html += "<table bordered striped>"
    html += "<tr><th>Группа товаров</th><th>Сумма</th><th>Доля</th></tr>"

    sorted_food = sorted(food_expenses.items(), key=lambda x: x[1], reverse=True)
    for subcat, val in sorted_food:
        share = (val / total_food * 100) if total_food > 0 else 0.0
        html += f"<tr><td>{subcat}</td><td><b>{val:.2f} ₽</b></td><td><i>{share:.1f}%</i></td></tr>"
    html += "</table>"

    return html
