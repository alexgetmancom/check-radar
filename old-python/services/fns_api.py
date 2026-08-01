import json
import logging
import os
import sqlite3
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from typing import Any, Optional

from config.settings import ALLOWED_USERS, BASE_URL, CREDENTIALS_FILE, DB_FILE, DEFAULT_USER_AGENT
from database.connection import is_receipt_exists, save_receipt_to_db

logger = logging.getLogger("fns_api")


def load_credentials() -> Optional[Any]:
    if not os.path.exists(CREDENTIALS_FILE):
        example = {
            "phone": "79639629392",
            "device_id": "СКОПИРУЙТЕ_ИЗ_БРАУЗЕРА",
            "refresh_token": "СКОПИРУЙТЕ_ИЗ_БРАУЗЕРА",
            "user_agent": DEFAULT_USER_AGENT,
        }
        with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
            json.dump(example, f, indent=2, ensure_ascii=False)
        return None

    with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_credentials(creds: Any) -> None:
    with open(CREDENTIALS_FILE, "w", encoding="utf-8") as f:
        json.dump(creds, f, indent=2, ensure_ascii=False)


def api_request(
    path: str, payload: dict[str, Any], token: Optional[str] = None, user_agent: str = DEFAULT_USER_AGENT
) -> dict[str, Any]:
    url = BASE_URL + path
    data = json.dumps(payload).encode("utf-8")

    max_retries = 3
    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json;charset=UTF-8")
        req.add_header("User-Agent", user_agent)
        if token:
            req.add_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(req, timeout=15) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            try:
                err_json = json.loads(body)
                err_msg = err_json.get("message", body)
            except Exception:
                err_msg = body

            logger.error(f"Ошибка API ФНС ({e.code}) на попытке {attempt + 1}: {err_msg}")

            # Если 400 или 401 — это ошибка сессии, ретраить бесполезно
            if e.code in [400, 401] or attempt == max_retries - 1:
                raise e
            time.sleep(2.0)
        except Exception as e:
            logger.error(f"Ошибка сети/таймаут на попытке {attempt + 1}: {e}")
            if attempt == max_retries - 1:
                raise e
            time.sleep(2.0)

    raise RuntimeError("Не удалось выполнить запрос к ФНС")


def refresh_access_token(creds: dict[str, Any], all_creds: Any) -> str:
    logger.info(f"Обновление токена доступа для {creds.get('phone')}...")
    payload = {
        "deviceInfo": {
            "appVersion": "1.0.0",
            "metaDetails": {"userAgent": creds.get("user_agent", DEFAULT_USER_AGENT)},
            "sourceDeviceId": creds["device_id"],
            "sourceType": "WEB",
        },
        "refreshToken": creds["refresh_token"],
    }

    try:
        resp = api_request("/v1/auth/token", payload, user_agent=creds.get("user_agent", DEFAULT_USER_AGENT))
    except urllib.error.HTTPError as e:
        if e.code in [400, 401]:
            logger.error(f"Сессия ФНС для аккаунта {creds.get('phone')} недействительна (HTTP {e.code}).")
            from utils.tg_client import send_tg_text_message

            for user_id in ALLOWED_USERS:
                send_tg_text_message(
                    user_id,
                    f"⚠️ <b>Сессия ФНС для аккаунта {creds.get('phone')} истекла!</b>\n"
                    f"Пожалуйста, авторизуйтесь на lkdr.nalog.ru через браузер, "
                    f"скопируйте новые параметры и обновите <code>credentials.json</code>.",
                )
        raise e

    if resp.get("refreshToken") and resp["refreshToken"] != creds["refresh_token"]:
        creds["refresh_token"] = resp["refreshToken"]
        save_credentials(all_creds)
        logger.info(f"Получен новый Refresh Token для {creds.get('phone')}.")

    return resp["token"]


def fetch_receipts(token: str, creds: dict[str, Any]) -> list[dict[str, Any]]:
    logger.info(f"Загрузка списка всех чеков для {creds.get('phone')}...")
    all_receipts = []
    offset = 0
    limit = 100
    while True:
        payload = {"limit": limit, "offset": offset}
        resp = api_request("/v1/receipt", payload, token=token, user_agent=creds.get("user_agent", DEFAULT_USER_AGENT))
        receipts = resp.get("receipts", [])
        all_receipts.extend(receipts)
        logger.info(f"Загружено {len(receipts)} чеков (смещение: {offset})...")
        if not resp.get("hasMore") or len(receipts) < limit:
            break
        offset += limit
    return all_receipts


def fetch_fiscal_data(token: str, receipt_key: str, creds: dict[str, Any]) -> Optional[dict[str, Any]]:
    payload = {"key": receipt_key}
    try:
        resp = api_request(
            "/v1/receipt/fiscal_data", payload, token=token, user_agent=creds.get("user_agent", DEFAULT_USER_AGENT)
        )
        return resp
    except Exception:
        return None


def sync_receipts_from_fns() -> int:
    logger.info("Запуск фоновой синхронизации...")
    creds_data = load_credentials()
    if not creds_data:
        logger.error("credentials.json не найден или пуст.")
        return -1

    if isinstance(creds_data, dict):
        accounts = [creds_data]
    else:
        accounts = creds_data

    total_new_count = 0

    from services.telegram_bot import (
        send_new_receipt_notification_sync as send_new_receipt_notification,
        update_dashboard_if_exists_sync as update_dashboard_if_exists,
    )

    for account in accounts:
        phone_label = account.get("phone", "Неизвестный номер")
        try:
            logger.info(f"Синхронизация аккаунта {phone_label}...")
            token = refresh_access_token(account, creds_data)
            receipts_list = fetch_receipts(token, account)

            receipts_list = sorted(receipts_list, key=lambda x: x.get("createdDate", ""))

            for r in receipts_list:
                if not is_receipt_exists(r["key"]):
                    logger.info(f"Скачиваем состав нового чека от {r.get('createdDate')}...")
                    fd = fetch_fiscal_data(token, r["key"], account)
                    save_receipt_to_db(r, fd, owner_phone=account.get("phone"))
                    total_new_count += 1

                    is_recent = False
                    created_date_str = r.get("createdDate")
                    if created_date_str:
                        try:
                            dt_clean = created_date_str.replace("Z", "").split("+")[0]
                            created_dt = datetime.fromisoformat(dt_clean)
                            if datetime.now() - created_dt < timedelta(days=2):
                                is_recent = True
                        except Exception as e:
                            logger.error(f"Ошибка парсинга даты чека: {e}")

                    total_db_count = 0
                    conn = sqlite3.connect(DB_FILE)
                    cur = conn.cursor()
                    cur.execute("SELECT COUNT(*) FROM receipts")
                    row = cur.fetchone()
                    if row:
                        total_db_count = row[0]
                    conn.close()

                    if total_db_count > 100 and is_recent:
                        for user_id in ALLOWED_USERS:
                            send_new_receipt_notification(user_id, r, fd, owner_phone=account.get("phone"))
                        time.sleep(1.0)
        except Exception as e:
            logger.error(f"Ошибка синхронизации аккаунта {phone_label}: {e}", exc_info=True)

    for user_id in ALLOWED_USERS:
        update_dashboard_if_exists(user_id)

    logger.info(f"Синхронизация завершена. Всего импортировано: {total_new_count}")
    return total_new_count
