from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from config import settings
from database import Database

dp = Dispatcher()
_db = None


def set_database(db):
    global _db
    _db = db


def main_menu(notifications_enabled=True):
    status = "ВКЛ" if notifications_enabled else "ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"🔔 Уведомления: {status}",
            callback_data="toggle_notifications",
        )],
        [InlineKeyboardButton(
            text="⚙️ Мои настройки",
            callback_data="settings",
        )],
    ])


def menu_text(notifications_enabled=True):
    status = "ВКЛ 🟢" if notifications_enabled else "ВЫКЛ 🔴"
    return (
        "🚗 <b>AutoHunter</b>\n\n"
        "Мониторинг автомобилей ниже рыночной цены.\n\n"
        f"🔔 Уведомления: <b>{status}</b>\n"
        f"📅 Год: <b>{settings.min_year}+</b>\n"
        f"📉 Минимальная скидка: <b>{settings.min_market_discount_percent:g}%</b>\n"
        f"🔎 Проверка: каждые <b>{settings.check_interval_seconds // 60} мин</b>\n\n"
        "Пока доступны объявления из <b>AUTO.RIA</b>."
    )


@dp.message(CommandStart())
async def start_handler(message: Message):
    if _db:
        await _db.add_subscriber(message.chat.id)
        enabled = await _db.notifications_enabled(message.chat.id)
    else:
        enabled = True

    await message.answer(
        menu_text(enabled),
        parse_mode="HTML",
        reply_markup=main_menu(enabled),
    )


@dp.callback_query(lambda c: c.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    if not _db:
        await callback.answer("База данных недоступна", show_alert=True)
        return

    enabled = await _db.toggle_notifications(callback.message.chat.id)
    await callback.message.edit_text(
        menu_text(enabled),
        parse_mode="HTML",
        reply_markup=main_menu(enabled),
    )
    await callback.answer(
        "Уведомления включены 🔔" if enabled else "Уведомления выключены 🔕"
    )


@dp.callback_query(lambda c: c.data == "settings")
async def settings_handler(callback: CallbackQuery):
    await callback.message.edit_text(
        "⚙️ <b>Мои настройки</b>\n\n"
        f"📅 Минимальный год: <b>{settings.min_year}</b>\n"
        f"📉 Минимальная скидка: <b>{settings.min_market_discount_percent:g}%</b>\n"
        "🌐 Источник: <b>AUTO.RIA</b>\n\n"
        "Индивидуальные фильтры по марке, модели, цене и пробегу "
        "добавим следующим этапом.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_menu")]
        ]),
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data == "back_menu")
async def back_menu_handler(callback: CallbackQuery):
    enabled = await _db.notifications_enabled(callback.message.chat.id) if _db else True
    await callback.message.edit_text(
        menu_text(enabled),
        parse_mode="HTML",
        reply_markup=main_menu(enabled),
    )
    await callback.answer()


@dp.message()
async def fallback_handler(message: Message):
    enabled = await _db.notifications_enabled(message.chat.id) if _db else True
    await message.answer(
        "Открой меню AutoHunter кнопкой ниже 👇",
        reply_markup=main_menu(enabled),
    )


async def run_bot():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    import asyncio
    from scanner import scanner_loop

    db = Database(settings.database_url)
    await db.connect()
    set_database(db)
    bot = Bot(token=settings.telegram_bot_token)
    task = asyncio.create_task(scanner_loop(bot, db))

    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await bot.session.close()
        await db.close()
