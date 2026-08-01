import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
import urllib.parse

from config.rules import get_item_category
from config.settings import ALLOWED_USERS
from database.connection import get_clean_receipts

# Инициализируем настройки логгера
from utils.logger import setup_logging
from utils.tg_client import send_tg_photo

setup_logging()
logger = logging.getLogger("send_test_chart")


def main():
    logger.info("Формирование отчета за Июль 2026 г. для всех пользователей...")

    # 1. Получаем чистые чеки за Июль 2026
    receipts = get_clean_receipts("2026-07-01T00:00:00", "2026-07-31T23:59:59")

    # Группируем траты по категориям
    cats = {}
    for _rkey, r in receipts.items():
        for item in r["items"]:
            name = item["name"]
            val = item["sum"]
            if name in ["Платеж", "Предоплата", "Аванс"]:
                continue
            cat = get_item_category(name, r["owner"])
            cats[cat] = cats.get(cat, 0.0) + val

    # Если реальных расходов в БД мало, генерируем красивые демо-данные для визуализации
    if not cats or len(cats) < 2:
        logger.info("Недостаточно расходов за Июль 2026 в базе данных. Генерируем тестовую диаграмму.")
        cats = {
            "Продукты питания и напитки": 15420.50,
            "Транспорт (Такси)": 3420.00,
            "Связь и интернет": 1250.00,
            "Товары для питомцев": 4500.00,
            "Разное / Прочее": 2300.00,
        }

    total_sum = sum(cats.values())
    sorted_cats = sorted(cats.items(), key=lambda x: x[1], reverse=True)

    labels = []
    data = []

    for cat, val in sorted_cats:
        share = (val / total_sum) * 100
        labels.append(f"{cat} ({share:.1f}%)")
        data.append(round(val, 2))

    # Настройки для QuickChart API (Chart.js v2-v3)
    chart_config = {
        "type": "doughnut",
        "data": {
            "labels": labels,
            "datasets": [
                {
                    "data": data,
                    "backgroundColor": [
                        "#5C6BC0",  # Indigo
                        "#26A69A",  # Teal
                        "#FFA726",  # Orange
                        "#EC407A",  # Pink
                        "#AB47BC",  # Purple
                        "#78909C",  # Blue grey
                    ],
                    "borderWidth": 2,
                    "borderColor": "#FFFFFF",
                }
            ],
        },
        "options": {
            "plugins": {"legend": {"position": "bottom", "labels": {"boxWidth": 15, "fontSize": 14}}},
            "title": {
                "display": True,
                "text": f"Расходы за Июль 2026 г. (Всего: {total_sum:.2f} ₽)",
                "fontSize": 18,
                "fontStyle": "bold",
                "padding": 20,
            },
        },
    }

    # Кодируем JSON конфиг в URL
    config_str = json.dumps(chart_config)
    encoded_config = urllib.parse.quote(config_str)
    chart_url = f"https://quickchart.io/chart?c={encoded_config}&w=600&h=450"

    # Формируем текстовую подпись под фото
    caption = "📊 <b>Финансовый отчет за Июль 2026 г.</b>\n"
    caption += f"💰 <b>Всего расходов: {total_sum:.2f} ₽</b>\n\n"
    for cat, val in sorted_cats:
        share = (val / total_sum) * 100
        caption += f"• <b>{cat}:</b> {val:.2f} ₽ (<i>{share:.1f}%</i>)\n"

    for user_id in ALLOWED_USERS:
        logger.info(f"Отправка диаграммы в Telegram для chat_id {user_id}...")
        resp = send_tg_photo(user_id, chart_url, caption=caption)
        if resp and resp.get("ok"):
            logger.info(f"[+] Диаграмма успешно отправлена для chat_id {user_id}!")
        else:
            logger.error(f"[-] Не удалось отправить диаграмму для chat_id {user_id}: {resp}")


if __name__ == "__main__":
    main()
