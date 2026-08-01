import base64
import html.parser
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Optional, Tuple

from config.settings import ALLOWED_USERS
from database.connection import is_receipt_exists, save_receipt_to_db, save_taxi_trip

logger = logging.getLogger("gmail_sync")

GMAIL_TOKEN_FILE = "gmail_token.json"
CLIENT_SECRET_FILE = "client_secret.json"


class EmailParser(html.parser.HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.tokens: list[Tuple[Optional[str], dict[str, str], str]] = []
        self.current_attrs: dict[str, str] = {}
        self.current_tag: Optional[str] = None

    def handle_starttag(self, tag: str, attrs: list[Tuple[str, Optional[str]]]) -> None:
        self.current_tag = tag
        self.current_attrs = {k: v or "" for k, v in attrs}

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.tokens.append((self.current_tag, self.current_attrs, text))

    def handle_endtag(self, tag: str) -> None:
        self.current_tag = None
        self.current_attrs = {}


def refresh_gmail_token() -> Optional[str]:
    if not os.path.exists(GMAIL_TOKEN_FILE) or not os.path.exists(CLIENT_SECRET_FILE):
        return None

    with open(GMAIL_TOKEN_FILE, "r") as f:
        tokens = json.load(f)

    if tokens.get("expires_at", 0) > int(time.time()) + 60:
        return tokens["access_token"]

    logger.info("Обновление Gmail Access Token...")
    with open(CLIENT_SECRET_FILE, "r") as f:
        config = json.load(f)["installed"]

    payload = {
        "refresh_token": tokens["refresh_token"],
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "grant_type": "refresh_token",
    }
    data = urllib.parse.urlencode(payload).encode("utf-8")

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        with urllib.request.urlopen(req) as resp:
            res = json.loads(resp.read().decode("utf-8"))

        tokens["access_token"] = res["access_token"]
        tokens["expires_at"] = int(time.time()) + res.get("expires_in", 3600)

        with open(GMAIL_TOKEN_FILE, "w") as f:
            json.dump(tokens, f, indent=2)

        logger.info("Gmail Access Token успешно обновлен.")
        return tokens["access_token"]
    except Exception as e:
        logger.error(f"Ошибка обновления Gmail токена: {e}")
        return None


def gmail_api_request(path: str) -> Optional[dict[str, Any]]:
    token = refresh_gmail_token()
    if not token:
        return None

    url = f"https://gmail.googleapis.com/gmail/v1{path}"

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.error(f"Ошибка Gmail API ({path}) на попытке {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                return None
            time.sleep(2.0)

    return None


def extract_html_body(payload: dict[str, Any]) -> str:
    def extract(part: dict[str, Any]) -> str:
        mime_type = part.get("mimeType", "")
        body_data = part.get("body", {}).get("data", "")
        if mime_type == "text/html" and body_data:
            return base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
        parts = part.get("parts", [])
        for p in parts:
            html = extract(p)
            if html:
                return html
        return ""

    html = extract(payload)
    if not html:
        body_data = payload.get("body", {}).get("data", "")
        if body_data:
            html = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
    return html


def parse_fasten_ride_html(html_body: str) -> Tuple[str, str, float]:
    parser = EmailParser()
    parser.feed(html_body)
    tokens = parser.tokens

    start_point = "Неизвестно"
    end_point = "Неизвестно"
    price = 0.0

    routes = []
    for _tag, attrs, text in tokens:
        if attrs.get("class") == "route__name":
            routes.append(text)
        if attrs.get("class") == "check__price" or "check__price" in attrs.get("class", ""):
            match = re.search(r"(\d+)", text.replace(" ", "").replace("\xa0", ""))
            if match:
                price = float(match.group(1))

    if len(routes) >= 1:
        start_point = routes[0]
    if len(routes) >= 2:
        end_point = routes[1]

    if price == 0.0:
        for _tag, _attrs, text in tokens:
            if "₽" in text:
                match = re.search(r"(\d+)", text.replace(" ", "").replace("\xa0", ""))
                if match:
                    price = float(match.group(1))
                    break

    return start_point, end_point, price


def parse_yandex_taxi_html(html_body: str) -> Tuple[str, str, float, str, float, int, float]:
    parser = EmailParser()
    parser.feed(html_body)
    tokens = parser.tokens

    start_point = "Неизвестно"
    end_point = "Неизвестно"
    price = 0.0
    tariff = "Эконом"
    distance = 0.0
    duration = 0
    tips = 0.0

    text_list = [t[2] for t in tokens]

    for i, text in enumerate(text_list):
        text_lower = text.lower()

        # Точки маршрута
        if "откуда" in text_lower or "адрес подачи" in text_lower or text == "А":
            if i + 1 < len(text_list):
                start_point = text_list[i + 1]
        if "куда" in text_lower or "адрес назначения" in text_lower or text == "Б":
            if i + 1 < len(text_list):
                end_point = text_list[i + 1]

        # Класс тарифа
        for t_class in ["эконом", "комфорт+", "комфорт", "бизнес", "ultima", "детский", "минивэн"]:
            if t_class in text_lower and len(text) < 15:
                tariff = text.capitalize()

        # Дистанция и длительность
        if "км" in text_lower or "km" in text_lower:
            match = re.search(r"(\d+(?:\.\d+)?)\s*(?:км|km)", text_lower)
            if match:
                distance = float(match.group(1))
        if "мин" in text_lower or "min" in text_lower:
            match = re.search(r"(\d+)\s*(?:мин|min)", text_lower)
            if match:
                duration = int(match.group(1))

        # Итоговая цена
        if "итого" in text_lower or "всего" in text_lower:
            if i + 1 < len(text_list):
                price_text = text_list[i + 1]
                match = re.search(r"(\d+(?:\.\d+)?)", price_text.replace(" ", "").replace("\xa0", ""))
                if match:
                    price = float(match.group(1))

        # Чаевые
        if "чаевые" in text_lower:
            if i + 1 < len(text_list):
                tips_text = text_list[i + 1]
                match = re.search(r"(\d+)", tips_text.replace(" ", "").replace("\xa0", ""))
                if match:
                    tips = float(match.group(1))

    # Резервные поиски, если не нашлось
    if price == 0.0:
        for text in text_list:
            if "₽" in text and ("итого" in text.lower() or "стоимость" in text.lower() or "оплата" in text.lower()):
                match = re.search(r"(\d+)", text.replace(" ", "").replace("\xa0", ""))
                if match:
                    price = float(match.group(1))
                    break

    if start_point == "Неизвестно" or end_point == "Неизвестно":
        possible_addresses = []
        for text in text_list:
            if any(
                marker in text.lower()
                for marker in ["ул.", "просп.", "д.", "проспект", "шоссе", "бульвар", "пер.", "переулок"]
            ):
                possible_addresses.append(text)
        if len(possible_addresses) >= 2:
            if start_point == "Неизвестно":
                start_point = possible_addresses[0]
            if end_point == "Неизвестно":
                end_point = possible_addresses[1]

    return start_point, end_point, price, tariff, distance, duration, tips


def parse_trytek_payment(snippet: str) -> float:
    price_match = re.search(r"Сумма\s*([\d\s]+)\s*₽", snippet)
    if price_match:
        price_str = price_match.group(1).replace(" ", "").replace("\xa0", "")
        return float(price_str)
    return 0.0


_cbr_rates_cache: dict[str, float] = {}
_cbr_cache_time: float = 0.0


def get_cbr_rates() -> dict[str, float]:
    global _cbr_rates_cache, _cbr_cache_time
    if _cbr_rates_cache and time.time() - _cbr_cache_time < 3600:
        return _cbr_rates_cache

    logger.info("Запрос курсов валют ЦБ РФ...")
    try:
        req = urllib.request.Request(
            "https://www.cbr-xml-daily.ru/daily_json.js", headers={"User-Agent": "Mozilla/5.0"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        rates = {}
        if "Valute" in data:
            for val_code in ["USD", "EUR"]:
                if val_code in data["Valute"]:
                    rates[val_code] = float(data["Valute"][val_code]["Value"])

        if rates.get("USD") and rates.get("EUR"):
            _cbr_rates_cache = rates
            _cbr_cache_time = time.time()
            logger.info(f"Курсы валют успешно обновлены: USD={rates['USD']:.2f} RUB, EUR={rates['EUR']:.2f} RUB")
            return rates
    except Exception as e:
        logger.error(f"Не удалось получить курсы ЦБ РФ: {e}. Используем fallback-курсы.")

    return {"USD": 90.0, "EUR": 98.0}


def convert_to_rub(amount: float, currency: str) -> float:
    rates = get_cbr_rates()
    if currency == "$":
        return amount * rates["USD"]
    elif currency == "€":
        return amount * rates["EUR"]
    return amount


def parse_timeweb_income(snippet: str) -> Tuple[float, str]:
    sum_match = re.search(r"зачислено\s*(\d+(?:\.\d+)?)\s*от", snippet)
    client_match = re.search(r"клиента\s*(\w+)", snippet)

    amount = 0.0
    client_id = "Неизвестно"

    if sum_match:
        amount = float(sum_match.group(1).replace(" ", "").replace("\xa0", ""))
    if client_match:
        client_id = client_match.group(1)

    return amount, client_id


def parse_stripe_receipt(subject: str, html_body: str) -> Tuple[str, float, str]:
    merchant = "Stripe Merchant"
    subject_lower = subject.lower()

    if "from" in subject_lower:
        match = re.search(r"from\s+([^\#]+)", subject, re.IGNORECASE)
        if match:
            merchant = match.group(1).strip()
    elif "от" in subject_lower:
        match = re.search(r"от\s+(.+)$", subject, re.IGNORECASE)
        if match:
            merchant = match.group(1).strip()

    for suffix in ["#", "№", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9"]:
        if suffix in merchant:
            merchant = merchant.split(suffix)[0].strip()

    parser = EmailParser()
    parser.feed(html_body)

    amount = 0.0
    currency = "$"

    for _tag, _attrs, text in parser.tokens:
        text_strip = text.strip()
        match = re.search(r"^([$€])\s*(\d+(?:\.\d+)?)$", text_strip)
        if match:
            currency = match.group(1)
            amount = float(match.group(2))
            break

    if amount == 0.0:
        for _tag, _attrs, text in parser.tokens:
            text_strip = text.strip()
            match = re.search(r"([$€])\s*(\d+(?:\.\d+)?)", text_strip)
            if match:
                currency = match.group(1)
                amount = float(match.group(2))
                break

    return merchant, amount, currency


def parse_spotify_plan(subject: str) -> Tuple[str, float]:
    plan_name = "Premium Duo"
    price = 14.99

    subject_lower = subject.lower()
    if "individual" in subject_lower:
        plan_name = "Premium Individual"
        price = 10.99
    elif "duo" in subject_lower:
        plan_name = "Premium Duo"
        price = 14.99
    elif "family" in subject_lower:
        plan_name = "Premium Family"
        price = 16.99
    elif "student" in subject_lower:
        plan_name = "Premium Student"
        price = 5.99

    return plan_name, price


def sync_gmail_receipts() -> int:
    logger.info("Запуск синхронизации чеков из Gmail...")
    if not os.path.exists(GMAIL_TOKEN_FILE):
        logger.info("Интеграция с Gmail не настроена (нет gmail_token.json).")
        return 0

    from services.telegram_bot import (
        send_new_receipt_notification_sync as send_new_receipt_notification,
        update_dashboard_if_exists_sync as update_dashboard_if_exists,
    )

    total_new_count = 0

    # 1. СИНХРОНИЗАЦИЯ YANDEX TAXI
    try:
        q_yandex = urllib.parse.quote('from:no-reply@taxi.yandex.ru subject:("Поездка" OR "Отчет")')
        res_yandex = gmail_api_request(f"/users/me/messages?q={q_yandex}&maxResults=10")
        if res_yandex and "messages" in res_yandex:
            for msg in res_yandex["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=full")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    html_body = extract_html_body(detail.get("payload", {}))
                    start_pt, end_pt, price, tariff, distance, duration, tips = parse_yandex_taxi_html(html_body)

                    if price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": price,
                            "kktOwner": 'ООО "ЯНДЕКС.ТАКСИ"',
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Поездка: {start_pt} -> {end_pt}",
                                    "price": price - tips,
                                    "quantity": 1.0,
                                    "sum": price - tips,
                                }
                            ]
                        }
                        if tips > 0:
                            fd["items"].append({"name": "Чаевые водителю", "price": tips, "quantity": 1.0, "sum": tips})

                        save_receipt_to_db(receipt, fd, owner_phone=None)

                        # Сохраняем метаданные такси
                        trip_data = {
                            "receipt_key": db_key,
                            "date": dt_iso,
                            "tariff_class": tariff,
                            "from_address": start_pt,
                            "to_address": end_pt,
                            "distance_km": distance,
                            "duration_mins": duration,
                            "fare_cost": price - tips,
                            "tips_cost": tips,
                            "total_cost": price,
                        }
                        save_taxi_trip(trip_data)

                        total_new_count += 1
                        logger.info(f"Импортирована поездка Яндекс.Такси на сумму {price} ₽ от {dt_iso}")

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone=None)
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта Яндекс.Такси: {e}", exc_info=True)

    # 2. СИНХРОНИЗАЦИЯ FASTEN TAXI
    try:
        q_fasten = urllib.parse.quote('from:no-reply@fasten.com subject:"Fasten: ride report"')
        res_fasten = gmail_api_request(f"/users/me/messages?q={q_fasten}&maxResults=10")
        if res_fasten and "messages" in res_fasten:
            for msg in res_fasten["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=full")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    html_body = extract_html_body(detail.get("payload", {}))
                    start_pt, end_pt, price = parse_fasten_ride_html(html_body)

                    if price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": price,
                            "kktOwner": "Fasten",
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Поездка: {start_pt} -> {end_pt}",
                                    "price": price,
                                    "quantity": 1.0,
                                    "sum": price,
                                }
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")

                        # Сохраняем в таблицу такси с дефолтными значениями
                        trip_data = {
                            "receipt_key": db_key,
                            "date": dt_iso,
                            "tariff_class": "Эконом",
                            "from_address": start_pt,
                            "to_address": end_pt,
                            "distance_km": 0.0,
                            "duration_mins": 0,
                            "fare_cost": price,
                            "tips_cost": 0.0,
                            "total_cost": price,
                        }
                        save_taxi_trip(trip_data)

                        total_new_count += 1
                        logger.info(f"Импортирована поездка Fasten на сумму {price} ₽ от {dt_iso}")

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта Fasten: {e}", exc_info=True)

    # 3. СИНХРОНИЗАЦИЯ ТРАЙТЕК (ИНТЕРНЕТ)
    try:
        q_trytek = urllib.parse.quote('from:inform@yoomoney.ru subject:"Информация о платеже" trytek.ru')
        res_trytek = gmail_api_request(f"/users/me/messages?q={q_trytek}&maxResults=10")
        if res_trytek and "messages" in res_trytek:
            for msg in res_trytek["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=full")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    snippet = detail.get("snippet", "")
                    price = parse_trytek_payment(snippet)

                    if price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": price,
                            "kktOwner": "Трайтек",
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {"name": "Оплата интернета Трайтек", "price": price, "quantity": 1.0, "sum": price}
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")
                        total_new_count += 1
                        logger.info(f"Импортирован платеж Трайтек на сумму {price} ₽ от {dt_iso}")

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта Трайтек: {e}", exc_info=True)

    # 4. СИНХРОНИЗАЦИЯ ДОХОДОВ TIMEWEB
    try:
        q_timeweb = urllib.parse.quote(
            'from:partner@timeweb.ru subject:"На Ваш счёт вебмастера зачислено вознаграждение"'
        )
        res_timeweb = gmail_api_request(f"/users/me/messages?q={q_timeweb}&maxResults=10")
        if res_timeweb and "messages" in res_timeweb:
            for msg in res_timeweb["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_timeweb_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=full")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    snippet = detail.get("snippet", "")
                    amount, client_id = parse_timeweb_income(snippet)

                    if amount > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": amount,
                            "kktOwner": "Timeweb (Доход)",
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Партнерское вознаграждение от клиента {client_id}",
                                    "price": amount,
                                    "quantity": 1.0,
                                    "sum": amount,
                                }
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")
                        total_new_count += 1
                        logger.info(f"Импортирован доход от Timeweb на сумму {amount} ₽ от {dt_iso}")

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта доходов Timeweb: {e}", exc_info=True)

    # 5. СИНХРОНИЗАЦИЯ SPOTIFY
    try:
        q_spotify = urllib.parse.quote('from:no-reply@spotify.com subject:"Your order confirmation for"')
        res_spotify = gmail_api_request(f"/users/me/messages?q={q_spotify}&maxResults=10")
        if res_spotify and "messages" in res_spotify:
            for msg in res_spotify["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_spotify_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=metadata&metadataHeaders=Subject")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    headers = detail.get("payload", {}).get("headers", [])
                    subject = ""
                    for h in headers:
                        if h.get("name", "").lower() == "subject":
                            subject = h.get("value", "")
                            break

                    plan_name, usd_price = parse_spotify_plan(subject)
                    rub_price = convert_to_rub(usd_price, "$")

                    if rub_price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": rub_price,
                            "kktOwner": "Spotify",
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Подписка Spotify: {plan_name} (${usd_price:.2f})",
                                    "price": rub_price,
                                    "quantity": 1.0,
                                    "sum": rub_price,
                                }
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")
                        total_new_count += 1
                        logger.info(
                            f"Импортирована подписка Spotify на сумму {rub_price:.2f} ₽ (${usd_price}) от {dt_iso}"
                        )

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта Spotify: {e}", exc_info=True)

    # 6. СИНХРОНИЗАЦИЯ STRIPE RECEIPTS (X, Anomaly и др.)
    try:
        q_stripe = urllib.parse.quote(
            'from:stripe.com subject:("Your receipt from" OR "Ваша квитанция" OR "квитанция")'
        )
        res_stripe = gmail_api_request(f"/users/me/messages?q={q_stripe}&maxResults=10")
        if res_stripe and "messages" in res_stripe:
            for msg in res_stripe["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_stripe_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=full")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    headers = detail.get("payload", {}).get("headers", [])
                    subject = ""
                    for h in headers:
                        if h.get("name", "").lower() == "subject":
                            subject = h.get("value", "")
                            break

                    html_body = extract_html_body(detail.get("payload", {}))
                    merchant, val_amount, val_currency = parse_stripe_receipt(subject, html_body)
                    rub_price = convert_to_rub(val_amount, val_currency)

                    if rub_price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": rub_price,
                            "kktOwner": merchant,
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Платеж {merchant} ({val_currency}{val_amount:.2f})",
                                    "price": rub_price,
                                    "quantity": 1.0,
                                    "sum": rub_price,
                                }
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")
                        total_new_count += 1
                        logger.info(
                            f"Импортирован платеж Stripe ({merchant}) на сумму {rub_price:.2f} ₽ ({val_currency}{val_amount}) от {dt_iso}"
                        )

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта Stripe: {e}", exc_info=True)

    # 7. СИНХРОНИЗАЦИЯ OPENAI (CHATGPT)
    try:
        q_openai = urllib.parse.quote('from:noreply@tm.openai.com subject:"ChatGPT — ваш новый план"')
        res_openai = gmail_api_request(f"/users/me/messages?q={q_openai}&maxResults=10")
        if res_openai and "messages" in res_openai:
            for msg in res_openai["messages"]:
                msg_id = msg["id"]
                db_key = f"gmail_openai_{msg_id}"

                if not is_receipt_exists(db_key):
                    detail = gmail_api_request(f"/users/me/messages/{msg_id}?format=metadata")
                    if not detail:
                        continue

                    internal_date = int(detail.get("internalDate", time.time() * 1000))
                    dt_iso = datetime.fromtimestamp(internal_date / 1000.0).isoformat()

                    usd_price = 20.00
                    rub_price = convert_to_rub(usd_price, "$")

                    if rub_price > 0:
                        receipt = {
                            "key": db_key,
                            "createdDate": dt_iso,
                            "receiveDate": dt_iso,
                            "totalSum": rub_price,
                            "kktOwner": "OpenAI (ChatGPT)",
                            "kktOwnerInn": "",
                            "buyer": "",
                        }
                        fd = {
                            "items": [
                                {
                                    "name": f"Подписка ChatGPT Plus (${usd_price:.2f})",
                                    "price": rub_price,
                                    "quantity": 1.0,
                                    "sum": rub_price,
                                }
                            ]
                        }

                        save_receipt_to_db(receipt, fd, owner_phone="79639629392")
                        total_new_count += 1
                        logger.info(
                            f"Импортирована подписка ChatGPT Plus на сумму {rub_price:.2f} ₽ ($20.00) от {dt_iso}"
                        )

                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, receipt, fd, owner_phone="79639629392")
                        time.sleep(1.0)
    except Exception as e:
        logger.error(f"Ошибка импорта OpenAI: {e}", exc_info=True)

    if total_new_count > 0:
        for user_id in ALLOWED_USERS:
            update_dashboard_if_exists(user_id)

    return total_new_count
