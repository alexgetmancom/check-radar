import logging
from typing import Any, Dict, Optional, Union

from aiogram import Bot
from aiogram.methods.base import TelegramMethod
from aiogram.types import BotCommand

logger = logging.getLogger("tg_client")


class SendRichMessage(TelegramMethod[Dict[str, Any]]):
    __returning__ = Dict[str, Any]
    __api_method__ = "sendRichMessage"

    chat_id: Union[int, str]
    rich_message: Dict[str, Any]
    reply_markup: Optional[Any] = None


class EditRichMessageText(TelegramMethod[Dict[str, Any]]):
    __returning__ = Dict[str, Any]
    __api_method__ = "editMessageText"

    chat_id: Union[int, str]
    message_id: int
    rich_message: Dict[str, Any]
    reply_markup: Optional[Any] = None


async def send_tg_rich_message_aiogram(
    bot: Bot, chat_id: int, html: str, reply_markup: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    try:
        method = SendRichMessage(chat_id=chat_id, rich_message={"html": html}, reply_markup=reply_markup)
        return await bot(method)
    except Exception as e:
        logger.error(f"Ошибка отправки rich_message: {e}")
        return None


async def edit_tg_rich_message_aiogram(
    bot: Bot, chat_id: int, message_id: int, html: str, reply_markup: Optional[Any] = None
) -> Optional[Dict[str, Any]]:
    try:
        method = EditRichMessageText(
            chat_id=chat_id, message_id=message_id, rich_message={"html": html}, reply_markup=reply_markup
        )
        return await bot(method)
    except Exception as e:
        logger.error(f"Ошибка редактирования rich_message: {e}")
        return None


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="menu", description="Главное меню трат"),
        BotCommand(command="stats", description="Аналитика трат за месяц (с графиком)"),
        BotCommand(command="taxi", description="Аналитика поездок на такси (с графиком)"),
        BotCommand(command="food", description="Аналитика трат на еду за текущий месяц"),
        BotCommand(command="find", description="Поиск чеков по названию товара (/find сыр)"),
        BotCommand(command="backup", description="Создать резервную копию базы данных"),
    ]
    await bot.set_my_commands(commands)
