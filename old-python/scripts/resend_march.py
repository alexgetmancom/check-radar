from config.settings import ALLOWED_USERS
from services.telegram_bot import send_tg_rich_message

CHAT_ID = list(ALLOWED_USERS)[0]  # Отправляем Алексу

march_data = {
    "month": "Март 2026",
    "total": "77 516.35 ₽",
    "categories": [
        ("Продукты питания и напитки", "42 406.59 ₽", "54.7%"),
        ("Связь и интернет-провайдеры", "10 341.89 ₽", "13.3%"),
        ("Товары для питомцев (корма)", "5 189.70 ₽", "6.7%"),
        ("Прочие покупки на Ozon", "5 023.48 ₽", "6.5%"),
        ("Разное / Прочее", "4 279.57 ₽", "5.5%"),
        ("Одежда и обувь", "3 344.15 ₽", "4.3%"),
        ("Доставка и сервисные сборы", "2 089.56 ₽", "2.7%"),
        ("Кафе и рестораны / Готовая еда", "1 334.35 ₽", "1.7%"),
        ("Хостинг, серверы и облака", "935.85 ₽", "1.2%"),
        ("Гигиена и бытовая химия", "822.99 ₽", "1.1%"),
        ("Объявления и реклама", "747.00 ₽", "1.0%"),
        ("Упаковка / Пакеты", "586.22 ₽", "0.8%"),
        ("Транспорт (Такси)", "316.00 ₽", "0.4%"),
        ("Подписки и лояльность", "99.00 ₽", "0.1%"),
    ],
}


def build_rich_table_message(m_data):
    html = f"<h1>📅 {m_data['month']}</h1>"
    html += f"<p>💰 <b>Всего расходов: {m_data['total']}</b></p>"
    html += "<table bordered striped>"
    html += "<tr><th>Категория трат</th><th>Сумма</th><th>Доля</th></tr>"
    for cat, val, pct in m_data["categories"]:
        html += f"<tr><td>{cat}</td><td><b>{val}</b></td><td><i>{pct}</i></td></tr>"
    html += "</table>"
    return html


def main():
    print("[*] Повторная отправка отчета за Март...")
    html = build_rich_table_message(march_data)
    resp = send_tg_rich_message(CHAT_ID, html)
    if resp and resp.get("ok"):
        print("[+] Успешно отправлен отчет за Март!")
    else:
        print(f"[-] Не удалось отправить отчет за Март: {resp}")


if __name__ == "__main__":
    main()
