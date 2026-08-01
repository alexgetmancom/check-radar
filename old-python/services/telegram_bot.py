import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from aiogram import Bot, F, Router
from aiogram.dispatcher.middlewares.base import BaseMiddleware
from aiogram.filters import Command, CommandObject
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)

from config.rules import simplify_store_name
from config.settings import ALLOWED_USERS
from database.connection import get_db, get_state, set_state
from services.analytics import (
    build_food_report,
    build_monthly_stats_report,
    build_taxi_report,
    build_weekly_report,
    categorize_items,
    check_spending_anomaly,
    get_clean_items,
)
from utils.formatters import format_receipt_html
from utils.tg_client import edit_tg_rich_message_aiogram, send_tg_rich_message_aiogram

logger = logging.getLogger("telegram_bot")

router = Router()


class AuthMiddleware(BaseMiddleware):
    async def __call__(self, handler: Any, event: TelegramObject, data: Dict[str, Any]) -> Any:
        user = data.get("event_from_user")
        if not user or user.id not in ALLOWED_USERS:
            if isinstance(event, Message):
                await event.answer("🔒 Доступ ограничен. Этот бот является персональным финансовым ассистентом.")
            elif isinstance(event, CallbackQuery):
                await event.answer("🔒 Доступ ограничен.", show_alert=True)
            return None
        return await handler(event, data)


router.message.outer_middleware(AuthMiddleware())
router.callback_query.outer_middleware(AuthMiddleware())


async def send_new_receipt_notification(
    bot: Bot, chat_id: int, receipt: dict[str, Any], fd: Optional[dict[str, Any]], owner_phone: Optional[str] = None
) -> None:
    html = format_receipt_html(receipt, fd, owner_phone=owner_phone)
    await send_tg_rich_message_aiogram(bot, chat_id, html)

    total_sum = float(receipt.get("totalSum", 0))
    anomaly = check_spending_anomaly(total_sum)
    if anomaly:
        today_sum, avg_daily, ratio = anomaly
        anomaly_html = (
            f"<h1>⚠️ Аномалия трат за день!</h1>"
            f"<p>Сегодня вы потратили уже <b>{today_sum:.2f} ₽</b>.</p>"
            f"<blockquote>Это в <b>{ratio:.1f} раз(а)</b> превышает ваш средний дневной расход за месяц ({avg_daily:.2f} ₽).</blockquote>"
        )
        await send_tg_rich_message_aiogram(bot, chat_id, anomaly_html)


def get_dashboard_html_and_markup() -> Tuple[str, InlineKeyboardMarkup]:
    now = datetime.now()

    # 1. Траты за текущий месяц
    start_of_month = now.strftime("%Y-%m-01T00:00:00")
    end_of_month = now.strftime("%Y-%m-%dT23:59:59")
    items_month = get_clean_items(start_of_month, end_of_month)
    sum_month = sum(categorize_items(items_month).values())

    # 2. Траты за текущую неделю vs прошлую неделю
    today = now.date()
    start_of_this_week = today - timedelta(days=today.weekday())
    start_of_last_week = start_of_this_week - timedelta(days=7)
    end_of_last_week = start_of_this_week - timedelta(seconds=1)

    dt_this_start = start_of_this_week.strftime("%Y-%m-%dT00:00:00")
    dt_last_start = start_of_last_week.strftime("%Y-%m-%dT00:00:00")
    dt_last_end = end_of_last_week.strftime("%Y-%m-%dT23:59:59")

    items_week = get_clean_items(dt_this_start, end_of_month)
    sum_week = sum(categorize_items(items_week).values())

    items_last_week = get_clean_items(dt_last_start, dt_last_end)
    sum_last_week = sum(categorize_items(items_last_week).values())

    # 3. Последний чек в базе
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT created_date, kkt_owner, total_sum
            FROM receipts
            ORDER BY created_date DESC
            LIMIT 1
        """)
        row = cursor.fetchone()

    last_receipt_str = "Нет трат"
    if row:
        dt_receipt, owner, total = row
        dt_receipt_formatted = datetime.fromisoformat(dt_receipt).strftime("%d.%m %H:%M")
        owner_clean = simplify_store_name(owner)
        last_receipt_str = f"🛍 {dt_receipt_formatted} · {owner_clean} · <b>{total:.0f} ₽</b>"

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

    html = f"📅 <b>{month_ru}:</b> <code>{sum_month:.2f} ₽</code>\n\n"
    html += f"🗓 <b>Неделя:</b> <code>{sum_week:.2f} ₽</code> <i>(vs {sum_last_week:.0f} ₽)</i>\n\n"
    html += f"{last_receipt_str}\n\n"
    html += f"<i>Обновлено: {now.strftime('%d.%m %H:%M')}</i>"

    markup = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Месяц", callback_data="dashboard_stats"),
                InlineKeyboardButton(text="📅 Неделя", callback_data="dashboard_week"),
            ],
            [
                InlineKeyboardButton(text="🔄 Обновить", callback_data="dashboard_sync"),
                InlineKeyboardButton(text="ℹ️ Справка", callback_data="dashboard_help"),
            ],
        ]
    )

    return html, markup


async def send_dashboard(bot: Bot, chat_id: int) -> None:
    html, markup = get_dashboard_html_and_markup()

    old_msg_id = get_state(f"dashboard_message_id_{chat_id}")
    if old_msg_id:
        try:
            await bot.delete_message(chat_id, int(old_msg_id))
        except Exception:
            pass

    resp = await bot.send_message(chat_id=chat_id, text=html, parse_mode="HTML", reply_markup=markup)
    if resp:
        new_msg_id = resp.message_id
        set_state(f"dashboard_message_id_{chat_id}", new_msg_id)


async def update_dashboard_if_exists(bot: Bot, chat_id: int) -> None:
    msg_id = get_state(f"dashboard_message_id_{chat_id}")
    if msg_id:
        html, markup = get_dashboard_html_and_markup()
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=int(msg_id), text=html, parse_mode="HTML", reply_markup=markup
            )
        except Exception:
            pass


def send_new_receipt_notification_sync(chat_id: int, receipt: dict[str, Any], fd: Optional[dict[str, Any]], owner_phone: Optional[str] = None) -> None:
    import config.settings as settings
    if settings.BOT_INSTANCE and settings.EVENT_LOOP:
        asyncio.run_coroutine_threadsafe(
            send_new_receipt_notification(settings.BOT_INSTANCE, chat_id, receipt, fd, owner_phone=owner_phone),
            settings.EVENT_LOOP
        )


def update_dashboard_if_exists_sync(chat_id: int) -> None:
    import config.settings as settings
    if settings.BOT_INSTANCE and settings.EVENT_LOOP:
        asyncio.run_coroutine_threadsafe(
            update_dashboard_if_exists(settings.BOT_INSTANCE, chat_id),
            settings.EVENT_LOOP
        )



@router.message(Command("start", "help", "menu"))
async def start_handler(message: Message, bot: Bot) -> None:
    await send_dashboard(bot, message.chat.id)


@router.message(Command("sync"))
async def sync_handler(message: Message, bot: Bot) -> None:
    status_msg = await message.answer("🔄 Запускаю синхронизацию с ФНС и почтой...")

    from services.fns_api import sync_receipts_from_fns
    from services.gmail_sync import sync_gmail_receipts

    new_count_fns = await asyncio.to_thread(sync_receipts_from_fns)
    new_count_gmail = await asyncio.to_thread(sync_gmail_receipts)

    if new_count_fns >= 0 or new_count_gmail >= 0:
        new_total = max(0, new_count_fns) + max(0, new_count_gmail)
        await status_msg.edit_text(
            f"✅ Синхронизация успешно завершена! Добавлено новых чеков: <b>{new_total}</b>.", parse_mode="HTML"
        )
    else:
        await status_msg.edit_text("❌ Произошла ошибка при подключении к ФНС или почте.")


@router.message(Command("week"))
async def week_handler(message: Message, bot: Bot) -> None:
    html = await asyncio.to_thread(build_weekly_report)
    await send_tg_rich_message_aiogram(bot, message.chat.id, html)


@router.message(Command("food"))
async def food_handler(message: Message, bot: Bot) -> None:
    html = await asyncio.to_thread(build_food_report)
    if html:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📊 Назад к общей статистике", callback_data="dashboard_stats")]
            ]
        )
        await send_tg_rich_message_aiogram(bot, message.chat.id, html, reply_markup=markup)
    else:
        await message.answer("🛒 В этом месяце расходов на продукты питания пока нет.")


@router.message(Command("taxi"))
async def taxi_handler(message: Message, bot: Bot) -> None:
    chart_url, html = await asyncio.to_thread(build_taxi_report)
    if html:
        if chart_url:
            await message.answer_photo(photo=chart_url)
        await send_tg_rich_message_aiogram(bot, message.chat.id, html)
    else:
        await message.answer("🚕 Расходов на такси в этом месяце пока нет.")


@router.message(Command("backup"))
async def backup_handler(message: Message, bot: Bot) -> None:
    await message.answer("📦 Подготавливаю резервную копию базы данных...")
    from config.settings import DB_FILE

    if os.path.exists(DB_FILE):
        caption = f"Резервная копия базы данных ({datetime.now().strftime('%d.%m.%Y %H:%M')})"
        try:
            await bot.send_document(chat_id=message.chat.id, document=FSInputFile(DB_FILE), caption=caption)
        except Exception:
            await message.answer("❌ Не удалось отправить файл базы данных.")
    else:
        await message.answer("❌ Файл базы данных не найден.")


@router.message(Command("find"))
async def find_handler(message: Message, command: CommandObject) -> None:
    query = command.args
    if not query:
        await message.answer("🔍 Введите поисковый запрос, например: <code>/find сыр</code>", parse_mode="HTML")
        return

    query = query.strip()

    def search_db(q: str) -> list[Any]:
        with get_db() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT r.created_date, r.kkt_owner, i.name, i.price
                FROM items i
                JOIN receipts r ON i.receipt_key = r.key
                WHERE i.name LIKE ?
                ORDER BY r.created_date DESC
                LIMIT 10
            """,
                (f"%{q}%",),
            )
            return cursor.fetchall()

    results = await asyncio.to_thread(search_db, query)

    if not results:
        await message.answer(f"🔍 По запросу «{query}» ничего не найдено.")
    else:
        html = f"<h1>🔍 Результаты поиска «{query}»</h1>"
        html += "<table bordered striped>"
        html += "<tr><th>Дата</th><th>Магазин</th><th>Товар</th><th>Цена</th></tr>"
        for dt, owner, name, price in results:
            dt_formatted = datetime.fromisoformat(dt).strftime("%d.%m.%y")
            owner_clean = simplify_store_name(owner)
            html += f"<tr><td>{dt_formatted}</td><td>{owner_clean}</td><td>{name[:25]}...</td><td><b>{price:.2f} ₽</b></td></tr>"
        html += "</table>"
        html += "<footer>Показаны последние 10 покупок</footer>"

        await send_tg_rich_message_aiogram(message.bot, message.chat.id, html)


@router.message(Command("stats"))
async def stats_handler(message: Message, bot: Bot) -> None:
    chart_url, html, total = await asyncio.to_thread(build_monthly_stats_report)
    if html:
        if chart_url:
            await message.answer_photo(photo=chart_url)
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🛒 Детализация продуктов", callback_data="dashboard_food_stats")]
            ]
        )
        await send_tg_rich_message_aiogram(bot, message.chat.id, html, reply_markup=markup)
    else:
        await message.answer("📊 В этом месяце расходов пока нет.")


@router.callback_query(F.data.startswith("dashboard_"))
async def callback_query_handler(query: CallbackQuery, bot: Bot) -> None:
    t_start = time.time()
    data = query.data
    chat_id = query.message.chat.id
    message_id = query.message.message_id

    if data == "dashboard_sync":
        await query.answer("🔄 Запущена синхронизация...")
        from services.fns_api import sync_receipts_from_fns
        from services.gmail_sync import sync_gmail_receipts

        new_count_fns = await asyncio.to_thread(sync_receipts_from_fns)
        new_count_gmail = await asyncio.to_thread(sync_gmail_receipts)

        if new_count_fns >= 0 or new_count_gmail >= 0:
            new_total = max(0, new_count_fns) + max(0, new_count_gmail)
            await query.answer(f"✅ Добавлено чеков: {new_total}")
            # Обновляем дашборд на месте
            html, markup = get_dashboard_html_and_markup()
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=html, parse_mode="HTML", reply_markup=markup
            )
        else:
            await query.answer("❌ Ошибка синхронизации", show_alert=True)

    elif data == "dashboard_stats":
        await query.answer()
        chart_url, html, total = await asyncio.to_thread(build_monthly_stats_report)
        if html:
            html_with_chart = html
            if chart_url:
                html_with_chart = f'<a href="{chart_url}">&#8203;</a>' + html
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🛒 Детализация продуктов", callback_data="dashboard_food_stats")],
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="dashboard_back")],
                ]
            )
            await edit_tg_rich_message_aiogram(bot, chat_id, message_id, html_with_chart, reply_markup=markup)
        else:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="📊 В этом месяце расходов пока нет.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="dashboard_back")]]
                ),
            )

    elif data == "dashboard_food_stats":
        await query.answer()
        html = await asyncio.to_thread(build_food_report)
        if html:
            markup = InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="📊 Назад к общей статистике", callback_data="dashboard_stats")],
                    [InlineKeyboardButton(text="🏠 В меню", callback_data="dashboard_back")],
                ]
            )
            await edit_tg_rich_message_aiogram(bot, chat_id, message_id, html, reply_markup=markup)
        else:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text="🛒 В этом месяце расходов на продукты питания пока нет.",
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="dashboard_back")]]
                ),
            )

    elif data == "dashboard_week":
        await query.answer()
        html = await asyncio.to_thread(build_weekly_report)
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="dashboard_back")]]
        )
        await edit_tg_rich_message_aiogram(bot, chat_id, message_id, html, reply_markup=markup)

    elif data == "dashboard_help":
        await query.answer()
        help_text = (
            "👋 <b>Finance Bot: Справка по командам</b>\n\n"
            "• Нажмите <b>🔄 Обновить</b> для синхронизации с ФНС.\n"
            "• Нажмите <b>📊 Месяц</b> или введите <code>/stats</code> для выгрузки структуры трат.\n"
            "• Введите <code>/food</code> для детальной статистики расходов на продукты.\n"
            "• Введите <code>/taxi</code> для подробного лога и аналитики поездок.\n"
            "• Введите <code>/backup</code> для бэкапа базы данных.\n"
            "• Нажмите <b>📅 Неделя</b> для сравнения с прошлой неделей.\n\n"
            "🔍 <b>Для поиска товара</b> используйте текстовую команду: \n"
            "<code>/find сыр</code>"
        )
        markup = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="dashboard_back")]]
        )
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=help_text, parse_mode="HTML", reply_markup=markup
        )

    elif data == "dashboard_back":
        await query.answer()
        html, markup = get_dashboard_html_and_markup()
        await bot.edit_message_text(
            chat_id=chat_id, message_id=message_id, text=html, parse_mode="HTML", reply_markup=markup
        )

    logger.info(f"[TIMING] Callback '{data}' processed in {time.time() - t_start:.4f} seconds")
