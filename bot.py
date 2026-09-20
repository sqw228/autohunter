from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import settings


dp = Dispatcher()


@dp.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "🚗 AutoHunter\n\n"
        "Бот запущен. Я готов к подключению поиска AUTO.RIA и OLX.\n\n"
        f"Минимальный год: {settings.min_year}\n"
        f"Порог ниже рынка: {settings.min_market_discount_percent:g}%\n\n"
        "Следующий этап — подключаем источник объявлений и базу данных."
    )


@dp.message()
async def fallback_handler(message: Message) -> None:
    await message.answer(
        "Используй /start. Настройки и поиск добавим следующим этапом."
    )


async def run_bot() -> None:
    bot = Bot(token=settings.telegram_bot_token)
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
