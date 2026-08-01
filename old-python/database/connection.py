import contextlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Generator, Optional

from config.settings import DB_FILE
from utils.deduplicator import filter_duplicate_receipts


@contextlib.contextmanager
def get_db() -> Generator[sqlite3.Connection, None, None]:
    db_path = Path(DB_FILE)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def init_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()

        # Таблица чеков
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS receipts (
                key TEXT PRIMARY KEY,
                created_date TEXT,
                receive_date TEXT,
                total_sum REAL,
                kkt_owner TEXT,
                kkt_owner_inn TEXT,
                buyer TEXT,
                owner_phone TEXT
            )
        """)

        # Попытка добавить колонку в существующую таблицу
        try:
            cursor.execute("ALTER TABLE receipts ADD COLUMN owner_phone TEXT")
        except sqlite3.OperationalError:
            pass

        # Таблица позиций в чеке
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_key TEXT,
                name TEXT,
                price REAL,
                quantity REAL,
                sum REAL,
                FOREIGN KEY (receipt_key) REFERENCES receipts(key) ON DELETE CASCADE
            )
        """)

        # Таблица метаданных такси-поездок
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS taxi_trips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_key TEXT UNIQUE,
                date TEXT,
                tariff_class TEXT,
                from_address TEXT,
                to_address TEXT,
                distance_km REAL,
                duration_mins INTEGER,
                fare_cost REAL,
                tips_cost REAL,
                total_cost REAL,
                FOREIGN KEY (receipt_key) REFERENCES receipts(key) ON DELETE CASCADE
            )
        """)

        # Создание индексов для оптимизации поиска (Стандарт 2026)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(created_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_receipt ON items(receipt_key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_taxi_trips_date ON taxi_trips(date)")


def init_state_db() -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bot_state (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def get_state(key: str, default: Any = None) -> Any:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM bot_state WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default


def set_state(key: str, value: Any) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR REPLACE INTO bot_state (key, value) VALUES (?, ?)", (key, str(value)))


def is_receipt_exists(receipt_key: str) -> bool:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT 1 FROM receipts WHERE key = ?", (receipt_key,))
        return cursor.fetchone() is not None


def save_receipt_to_db(
    receipt: dict[str, Any], fiscal_data: Optional[dict[str, Any]], owner_phone: Optional[str] = None
) -> None:
    try:
        total_sum = float(receipt.get("totalSum", 0))
    except ValueError:
        total_sum = 0.0

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO receipts (key, created_date, receive_date, total_sum, kkt_owner, kkt_owner_inn, buyer, owner_phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                receipt["key"],
                receipt.get("createdDate"),
                receipt.get("receiveDate"),
                total_sum,
                receipt.get("kktOwner"),
                receipt.get("kktOwnerInn"),
                receipt.get("buyer"),
                owner_phone,
            ),
        )

        if fiscal_data and "items" in fiscal_data:
            cursor.execute("DELETE FROM items WHERE receipt_key = ?", (receipt["key"],))
            for item in fiscal_data["items"]:
                cursor.execute(
                    """
                    INSERT INTO items (receipt_key, name, price, quantity, sum)
                    VALUES (?, ?, ?, ?, ?)
                """,
                    (receipt["key"], item.get("name"), item.get("price"), item.get("quantity"), item.get("sum")),
                )


def save_taxi_trip(trip_data: dict[str, Any]) -> None:
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT OR REPLACE INTO taxi_trips (
                receipt_key, date, tariff_class, from_address, to_address,
                distance_km, duration_mins, fare_cost, tips_cost, total_cost
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                trip_data["receipt_key"],
                trip_data["date"],
                trip_data["tariff_class"],
                trip_data["from_address"],
                trip_data["to_address"],
                trip_data["distance_km"],
                trip_data["duration_mins"],
                trip_data["fare_cost"],
                trip_data["tips_cost"],
                trip_data["total_cost"],
            ),
        )


def get_clean_receipts(start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    """
    Получает очищенный список чеков за период (без дубликатов).
    Возвращает словарь структурированных чеков.
    """
    query = """
        SELECT r.key, r.created_date, r.kkt_owner, r.total_sum, r.owner_phone,
               i.name, i.price, i.quantity, i.sum
        FROM receipts r
        JOIN items i ON r.key = i.receipt_key
    """
    params = []

    if start_date or end_date:
        conditions = []
        if start_date:
            conditions.append("r.created_date >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("r.created_date <= ?")
            params.append(end_date)
        query += " WHERE " + " AND ".join(conditions)

    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        rows = cursor.fetchall()

    receipts = {}
    for rkey, dt, owner, total_sum, owner_phone, item_name, price, qty, val in rows:
        if rkey not in receipts:
            receipts[rkey] = {
                "date": datetime.fromisoformat(dt),
                "owner": owner,
                "total_sum": total_sum,
                "owner_phone": owner_phone,
                "items": [],
            }
        receipts[rkey]["items"].append({"name": item_name, "price": price, "qty": qty, "sum": val})

    ignored_keys = filter_duplicate_receipts(receipts)
    return {k: v for k, v in receipts.items() if k not in ignored_keys}
