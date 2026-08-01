import asyncio
import logging
from datetime import datetime, timedelta

from utils.logger import setup_logging

# Инициализируем логирование до импорта других сервисов, чтобы они могли его использовать
setup_logging()
logger = logging.getLogger("main")

from aiogram import Bot, Dispatcher

from config.settings import ALLOWED_USERS, BOT_TOKEN
from database.connection import get_state, init_db, init_state_db, set_state
from services.fns_api import sync_receipts_from_fns
from services.telegram_bot import router
from utils.tg_client import send_tg_rich_message_aiogram, setup_bot_commands


async def cron_scheduler_async(bot: Bot) -> None:
    logger.info("Асинхронный планировщик авто-синхронизации запущен.")
    while True:
        try:
            from zoneinfo import ZoneInfo

            now_msk = datetime.now(ZoneInfo("Europe/Moscow"))

            # 1. Фоновая авто-синхронизация КАЖДЫЙ ЧАС
            last_sync_str = get_state("last_sync_time")
            should_sync = False
            if not last_sync_str:
                should_sync = True
            else:
                last_sync = datetime.fromisoformat(last_sync_str)
                if last_sync.tzinfo is None:
                    last_sync = last_sync.replace(tzinfo=ZoneInfo("Europe/Moscow"))
                if now_msk - last_sync > timedelta(hours=1):
                    should_sync = True

            if should_sync:
                logger.info("Запуск фоновой синхронизации чеков...")
                await asyncio.to_thread(sync_receipts_from_fns)
                try:
                    from services.gmail_sync import sync_gmail_receipts

                    await asyncio.to_thread(sync_gmail_receipts)
                except Exception as e:
                    logger.error(f"Ошибка фонового Gmail импорта: {e}", exc_info=True)
                set_state("last_sync_time", now_msk.isoformat())

            # 2. Еженедельный отчет в Воскресенье в 21:00 по МСК (UTC+3)
            if now_msk.weekday() == 6 and now_msk.hour == 21:
                last_weekly_report = get_state("last_weekly_report_date")
                today_str = now_msk.date().isoformat()
                if last_weekly_report != today_str:
                    logger.info("Отправка автоматического еженедельного отчета всем пользователям...")
                    from services.analytics import build_weekly_report

                    html_report = await asyncio.to_thread(build_weekly_report)
                    for user_id in ALLOWED_USERS:
                        await send_tg_rich_message_aiogram(bot, user_id, html_report)
                    set_state("last_weekly_report_date", today_str)

        except Exception as e:
            logger.error(f"Ошибка в планировщике: {e}", exc_info=True)

        await asyncio.sleep(60)


async def main() -> None:
    init_db()
    init_state_db()

    bot = Bot(token=BOT_TOKEN)
    
    # Сохраняем инстанс бота и event loop для фоновых потоков синхронизации
    import config.settings as settings
    settings.BOT_INSTANCE = bot
    settings.EVENT_LOOP = asyncio.get_running_loop()

    dp = Dispatcher()
    dp.include_router(router)

    try:
        await setup_bot_commands(bot)
        logger.info("Меню команд бота успешно настроено.")
    except Exception as e:
        logger.error(f"Ошибка настройки меню команд: {e}")

    # Запускаем фоновый планировщик как асинхронную задачу
    asyncio.create_task(cron_scheduler_async(bot))

    logger.info("Бот успешно запущен в асинхронном режиме. Нажмите Ctrl+C для выхода.")
    try:
        # Запускаем polling
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Ошибка при работе бота: {e}", exc_info=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен.")
