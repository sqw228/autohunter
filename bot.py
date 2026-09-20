from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import Message
from config import settings
from database import Database

dp=Dispatcher()
_db=None

def set_database(db):
    global _db
    _db=db

@dp.message(CommandStart())
async def start_handler(message:Message):
    if _db: await _db.add_subscriber(message.chat.id)
    await message.answer("🚗 <b>AutoHunter</b>\n\nМониторинг AUTO.RIA включён.\n"+f"Минимальный год: <b>{settings.min_year}</b>\n"+f"Порог ниже рынка: <b>{settings.min_market_discount_percent:g}%</b>\n"+f"Проверка: каждые <b>{settings.check_interval_seconds//60} мин</b>\n\n"+"Я буду присылать найденные объявления, когда цена заметно ниже рыночной медианы.",parse_mode="HTML")

@dp.message()
async def fallback_handler(message:Message): await message.answer("Используй /start.")

async def run_bot():
    if not settings.database_url: raise RuntimeError("DATABASE_URL is not configured")
    import asyncio
    from scanner import scanner_loop
    db=Database(settings.database_url)
    await db.connect()
    set_database(db)
    bot=Bot(token=settings.telegram_bot_token)
    task=asyncio.create_task(scanner_loop(bot,db))
    try: await dp.start_polling(bot)
    finally:
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        await bot.session.close()
        await db.close()
