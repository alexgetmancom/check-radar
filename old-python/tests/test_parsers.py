import os
import sys

# Добавляем корень проекта в путь поиска модулей
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from database.connection import get_db, init_db, save_taxi_trip
from services.gmail_sync import parse_fasten_ride_html, parse_yandex_taxi_html

# 1. Тестируем парсинг Yandex Taxi HTML
yandex_mock_html = """
<html>
<body>
  <div>Отчет о поездке на такси</div>
  <table>
    <tr><td>Откуда</td><td>ул. Ленина, д. 10</td></tr>
    <tr><td>Куда</td><td>просп. Мира, д. 25</td></tr>
    <tr><td>Тариф</td><td>Комфорт+</td></tr>
    <tr><td>Дистанция</td><td>14.2 км</td></tr>
    <tr><td>Время в пути</td><td>32 мин</td></tr>
    <tr><td>Итого</td><td>750.50 ₽</td></tr>
    <tr><td>Чаевые водителю</td><td>50 ₽</td></tr>
  </table>
</body>
</html>
"""

# 2. Тестируем парсинг Fasten HTML
fasten_mock_html = """
<html>
<body>
  <table>
    <tr><td class="route__name">Аэропорт Домодедово</td></tr>
    <tr><td class="route__name">ул. Тверская, 12</td></tr>
    <tr><td class="check__price">₽ 1850</td></tr>
  </table>
</body>
</html>
"""


def test() -> None:
    print("[*] Запуск тестов парсинга HTML...")

    # Тест Яндекс.Такси
    start, end, price, tariff, dist, dur, tips = parse_yandex_taxi_html(yandex_mock_html)
    print(f"Яндекс.Такси: {start} -> {end} | {price}₽ | Тариф: {tariff} | {dist}км | {dur}мин | Чаевые: {tips}₽")
    assert start == "ул. Ленина, д. 10"
    assert end == "просп. Мира, д. 25"
    assert price == 750.50
    assert tariff == "Комфорт+"
    assert dist == 14.2
    assert dur == 32
    assert tips == 50.0
    print("[+] Тест Яндекс.Такси пройден!")

    # Тест Fasten
    f_start, f_end, f_price = parse_fasten_ride_html(fasten_mock_html)
    print(f"Fasten: {f_start} -> {f_end} | {f_price}₽")
    assert f_start == "Аэропорт Домодедово"
    assert f_end == "ул. Тверская, 12"
    assert f_price == 1850.0
    print("[+] Тест Fasten пройден!")

    # Тест работы с БД
    init_db()
    trip_data = {
        "receipt_key": "test_receipt_key_123",
        "date": "2026-07-04T12:00:00",
        "tariff_class": tariff,
        "from_address": start,
        "to_address": end,
        "distance_km": dist,
        "duration_mins": dur,
        "fare_cost": price - tips,
        "tips_cost": tips,
        "total_cost": price,
    }
    save_taxi_trip(trip_data)

    # Читаем обратно
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM taxi_trips WHERE receipt_key = 'test_receipt_key_123'")
        row = cursor.fetchone()

    print(f"Запись в БД: {row}")
    assert row is not None
    assert row[1] == "test_receipt_key_123"
    assert row[3] == "Комфорт+"
    assert row[4] == "ул. Ленина, д. 10"
    assert row[5] == "просп. Мира, д. 25"
    assert row[6] == 14.2
    assert row[7] == 32
    assert row[8] == 700.5
    assert row[9] == 50.0
    assert row[10] == 750.5

    # Удаляем тест
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM taxi_trips WHERE receipt_key = 'test_receipt_key_123'")

    print("[+] Тест работы с БД пройден!")

    # 4. Тест парсера Timeweb
    from services.gmail_sync import parse_timeweb_income

    tw_snippet = "Здравствуйте. На Ваш счёт вебмастера (ID 130919) зачислено 454 от клиента wr995583 (тариф VDS). Ваш текущий баланс: 9617.0 руб."
    tw_sum, tw_client = parse_timeweb_income(tw_snippet)
    print(f"Timeweb Income: {tw_sum} | Client: {tw_client}")
    assert tw_sum == 454.0
    assert tw_client == "wr995583"
    print("[+] Тест парсера Timeweb пройден!")

    # 5. Тест парсера Stripe (X Developer Platform, Anomaly)
    from services.gmail_sync import parse_stripe_receipt

    stripe_html_x = """
    <html>
      <body>
        <div>Your receipt from X Developer Platform</div>
        <div>$5.00</div>
        <div>Paid June 21, 2026</div>
      </body>
    </html>
    """
    stripe_merchant, stripe_sum, stripe_currency = parse_stripe_receipt(
        "Your receipt from X Developer Platform #2854-7093", stripe_html_x
    )
    print(f"Stripe: {stripe_merchant} | Sum: {stripe_sum} | Currency: {stripe_currency}")
    assert stripe_merchant == "X Developer Platform"
    assert stripe_sum == 5.00
    assert stripe_currency == "$"
    print("[+] Тест парсера Stripe X пройден!")

    # 6. Тест парсера Spotify
    from services.gmail_sync import parse_spotify_plan

    spotify_plan, spotify_price = parse_spotify_plan('Your order confirmation for "Premium Duo"')
    print(f"Spotify: {spotify_plan} | Price: {spotify_price}")
    assert spotify_plan == "Premium Duo"
    assert spotify_price == 14.99
    print("[+] Тест парсера Spotify пройден!")

    # 7. Тест конвертера валют
    from services.gmail_sync import convert_to_rub

    usd_in_rub = convert_to_rub(10.0, "$")
    print(f"10 USD in RUB: {usd_in_rub}")
    assert usd_in_rub >= 500.0
    print("[+] Тест конвертера валют пройден!")


if __name__ == "__main__":
    test()
