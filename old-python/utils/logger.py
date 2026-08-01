import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logging():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_dir = os.path.join(base_dir, "data")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "bot.log")

    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Очистим старые обработчики, если они есть (для предотвращения дублирования при повторном импорте)
    logger.handlers.clear()

    # Форматирование логов
    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s [%(name)s:%(lineno)d] %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Вывод в консоль (sys.stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Вывод в файл с автоматической ротацией (максимум 5 МБ, хранить до 3 файлов бэкапа)
    file_handler = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
