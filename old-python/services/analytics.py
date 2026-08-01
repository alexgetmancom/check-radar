import json
import urllib.parse
from datetime import datetime, timedelta

from config.rules import get_food_subcategory, get_item_category
from database.connection import get_clean_receipts, get_db, get_state, set_state
from utils.formatters import format_food_stats, format_monthly_stats, format_weekly_report


def check_spending_anomaly(new_receipt_sum):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT SUM(total_sum)
            FROM receipts
            WHERE created_date >= date('now', '-30 days')
              AND created_date < date('now')
        """)
        row = cursor.fetchone()
        total_30days = row[0] if row and row[0] is not None else 0.0
        avg_daily = total_30days / 30.0

        cursor.execute("""
            SELECT SUM(total_sum)
            FROM receipts
            WHERE created_date >= date('now')
        """)
        row = cursor.fetchone()
        today_sum = (row[0] if row and row[0] is not None else 0.0) + new_receipt_sum

    if avg_daily > 200.0 and today_sum > 3 * avg_daily:
        today_str = datetime.now().date().isoformat()
        last_warning = get_state("last_anomaly_warning_date")
        if last_warning != today_str:
            set_state("last_anomaly_warning_date", today_str)
            ratio = today_sum / avg_daily
            return today_sum, avg_daily, ratio
    return None


def get_clean_items(start_date, end_date):
    receipts = get_clean_receipts(start_date, end_date)
    valid_items = []
    for _rkey, r in receipts.items():
        for it in r["items"]:
            if it["name"] in ["Платеж", "Предоплата", "Аванс"]:
                continue
            valid_items.append((r["owner"], it["name"], it["sum"], r.get("owner_phone")))
    return valid_items


def categorize_items(items_list):
    grouped = {}
    for owner, name, val, _owner_phone in items_list:
        matched = get_item_category(name, owner)
        grouped[matched] = grouped.get(matched, 0.0) + val
    return grouped


def build_weekly_report():
    now = datetime.now()
    today = now.date()
    start_of_this_week = today - timedelta(days=today.weekday())
    start_of_last_week = start_of_this_week - timedelta(days=7)

    end_of_last_week = start_of_this_week - timedelta(seconds=1)
    end_of_this_week = start_of_this_week + timedelta(days=7) - timedelta(seconds=1)

    dt_this_start = start_of_this_week.strftime("%Y-%m-%dT00:00:00")
    dt_this_end = end_of_this_week.strftime("%Y-%m-%dT23:59:59")
    dt_last_start = start_of_last_week.strftime("%Y-%m-%dT00:00:00")
    dt_last_end = end_of_last_week.strftime("%Y-%m-%dT23:59:59")

    items_this = get_clean_items(dt_this_start, dt_this_end)
    items_last = get_clean_items(dt_last_start, dt_last_end)

    cats_this = categorize_items(items_this)
    cats_last = categorize_items(items_last)

    total_this = sum(val for cat, val in cats_this.items() if cat != "Доходы")
    total_last = sum(val for cat, val in cats_last.items() if cat != "Доходы")

    items_this_clean = [(owner, name, val) for owner, name, val, owner_phone in items_this]

    html = format_weekly_report(
        start_of_this_week,
        today,
        start_of_last_week,
        end_of_last_week,
        cats_this,
        cats_last,
        total_this,
        total_last,
        items_this_clean,
    )
    return html


def build_food_report():
    now = datetime.now()
    start_of_month = now.strftime("%Y-%m-01T00:00:00")
    end_of_month = now.strftime("%Y-%m-%dT23:59:59")

    items = get_clean_items(start_of_month, end_of_month)
    food_expenses = {}
    total_food = 0.0

    for owner, name, val, _owner_phone in items:
        subcat = get_food_subcategory(name, owner)
        if subcat:
            food_expenses[subcat] = food_expenses.get(subcat, 0.0) + val
            total_food += val

    if total_food == 0:
        return None

    html = format_food_stats(total_food, food_expenses)
    return html


def build_monthly_stats_report():
    now = datetime.now()
    start_of_month = now.strftime("%Y-%m-01T00:00:00")
    end_of_month = now.strftime("%Y-%m-%dT23:59:59")

    items = get_clean_items(start_of_month, end_of_month)
    cats = categorize_items(items)
    total = sum(val for cat, val in cats.items() if cat != "Доходы")

    if total == 0 and cats.get("Доходы", 0.0) == 0:
        return None, None, 0.0

    total_lesha = sum(
        val
        for owner, name, val, owner_phone in items
        if owner_phone == "79639629392" and get_item_category(name, owner) != "Доходы"
    )
    total_masha = sum(
        val
        for owner, name, val, owner_phone in items
        if owner_phone == "79013652064" and get_item_category(name, owner) != "Доходы"
    )

    sorted_cats = sorted([(cat, val) for cat, val in cats.items() if cat != "Доходы"], key=lambda x: x[1], reverse=True)
    labels = []
    data = []
    for cat, val in sorted_cats:
        share = (val / total * 100) if total > 0 else 0.0
        labels.append(f"{cat} ({share:.1f}%)")
        data.append(round(val, 2))

    chart_config = {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [
                {"data": data, "backgroundColor": ["#5C6BC0", "#26A69A", "#FFA726", "#EC407A", "#AB47BC", "#78909C"]}
            ],
        },
        "options": {"title": {"display": True, "text": f"Расходы за текущий месяц (Итого: {total:.0f} ₽)"}},
    }

    config_str = json.dumps(chart_config)
    encoded_config = urllib.parse.quote(config_str)
    chart_url = f"https://quickchart.io/chart?c={encoded_config}&w=600&h=450"

    html = format_monthly_stats(total, cats, total_lesha=total_lesha, total_masha=total_masha)
    return chart_url, html, total


def build_taxi_report():
    now = datetime.now()
    start_of_month = now.strftime("%Y-%m-01")

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COUNT(*), SUM(total_cost), SUM(distance_km), SUM(duration_mins), SUM(tips_cost)
            FROM taxi_trips
            WHERE date >= ?
        """,
            (start_of_month,),
        )
        row = cursor.fetchone()

    if not row or row[0] == 0:
        return None, None

    count, total_cost, total_dist, total_dur, total_tips = row
    total_cost = total_cost or 0.0
    total_dist = total_dist or 0.0
    total_dur = total_dur or 0.0
    total_tips = total_tips or 0.0

    avg_price_km = total_cost / total_dist if total_dist > 0 else 0.0

    # Популярный тариф
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tariff_class, COUNT(*) as c
            FROM taxi_trips
            WHERE date >= ?
            GROUP BY tariff_class
            ORDER BY c DESC
            LIMIT 1
        """,
            (start_of_month,),
        )
        t_row = cursor.fetchone()
        popular_tariff = t_row[0] if t_row else "Неизвестно"

    # Топ-3 адресов назначения
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT to_address, COUNT(*) as c
            FROM taxi_trips
            WHERE date >= ? AND to_address != 'Неизвестно'
            GROUP BY to_address
            ORDER BY c DESC
            LIMIT 3
        """,
            (start_of_month,),
        )
        addr_rows = cursor.fetchall()

    chart_url = None
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT tariff_class, SUM(total_cost)
            FROM taxi_trips
            WHERE date >= ?
            GROUP BY tariff_class
        """,
            (start_of_month,),
        )
        tariff_costs = cursor.fetchall()

    if len(tariff_costs) > 1:
        labels = [f"{t} ({c:.0f} ₽)" for t, c in tariff_costs]
        data = [round(c, 2) for t, c in tariff_costs]
        chart_config = {
            "type": "doughnut",
            "data": {
                "labels": labels,
                "datasets": [{"data": data, "backgroundColor": ["#5C6BC0", "#26A69A", "#FFA726", "#EC407A"]}],
            },
            "options": {"title": {"display": True, "text": "Траты на такси по тарифам"}},
        }
        config_str = json.dumps(chart_config)
        encoded_config = urllib.parse.quote(config_str)
        chart_url = f"https://quickchart.io/chart?c={encoded_config}&w=400&h=300"

    month_ru = [
        "Январь",
        "Февраль",
        "Март",
        "Апрель",
        "Май",
        "Июнь",
        "Июль",
        "Август",
        "Сентябрь",
        "Октябрь",
        "Ноябрь",
        "Декабрь",
    ][now.month - 1]

    html = f"<h1>🚕 Статистика поездок: {month_ru} 2026</h1>"
    html += f"<p>💰 <b>Всего потрачено:</b> {total_cost:.2f} ₽ (Чаевые: {total_tips:.0f} ₽)</p>"
    html += f"<p>🛣 <b>Общий пробег:</b> {total_dist:.1f} км</p>"
    html += f"<p>⏱ <b>Время в пути:</b> {total_dur:.0f} мин</p>"
    html += f"<p>💳 <b>Средняя цена 1 км:</b> {avg_price_km:.2f} ₽/км</p>"
    html += f"<p>🚗 <b>Частый тариф:</b> {popular_tariff}</p>"

    if addr_rows:
        html += "<h3>📍 Популярные направления:</h3><ul>"
        for addr, count_addr in addr_rows:
            addr_short = addr.split(",")[0] if "," in addr else addr
            html += f"<li><b>{count_addr} раз(а)</b> — {addr_short}</li>"
        html += "</ul>"

    return chart_url, html
