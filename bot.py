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


def main_menu(enabled=True):
    status = "ВКЛ" if enabled else "ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 Уведомления: {status}", callback_data="toggle_notifications")],
        [InlineKeyboardButton(text="⚙️ Мои настройки", callback_data="settings")],
    ])


def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Минимальный год", callback_data="set_year")],
        [InlineKeyboardButton(text="📉 Минимальная скидка", callback_data="set_discount")],
        [InlineKeyboardButton(text="🛣 Максимальный пробег", callback_data="set_mileage")],
        [InlineKeyboardButton(text="💰 Максимальная цена", callback_data="set_price")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_menu")],
    ])


def choices_menu(kind):
    choices = {
        "year": [("2012+", 2012), ("2015+", 2015), ("2018+", 2018), ("2020+", 2020), ("2022+", 2022)],
        "discount": [("10%", 10), ("15%", 15), ("20%", 20), ("25%", 25), ("30%", 30)],
        "mileage": [("Без ограничения", None), ("100 000 км", 100000), ("150 000 км", 150000), ("200 000 км", 200000), ("250 000 км", 250000)],
        "price": [("Без ограничения", None), ("$10 000", 10000), ("$20 000", 20000), ("$30 000", 30000), ("$50 000", 50000)],
    }
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=label, callback_data=f"choose_{kind}_{value if value is not None else 'none'}")]
        for label, value in choices[kind]
    ] + [[InlineKeyboardButton(text="◀️ Назад", callback_data="settings")]])


def settings_text(s):
    mileage = f"{s['max_mileage_km']:,} км".replace(",", " ") if s['max_mileage_km'] else "без ограничения"
    price = f"${s['max_price_usd']:,.0f}".replace(",", " ") if s['max_price_usd'] else "без ограничения"
    return (
        "⚙️ <b>Мои настройки</b>\n\n"
        f"📅 Минимальный год: <b>{s['min_year}+</b>\n"
        f"📉 Минимальная скидка: <b>{s['min_discount']:g}%</b>\n"
        f"🛣 Максимальный пробег: <b>{mileage}</b>\n"
        f"💰 Максимальная цена: <b>{price}</b>\n"
        "🌐 Источник: <b>AUTO.RIA</b>"
    )


def menu_text(enabled, s):
    status = "ВКЛ 🟢" if enabled else "ВЫКЛ 🔴"
    return (
        "🚗 <b>AutoHunter</b>\n\n"
        "Мониторинг автомобилей ниже рыночной цены.\n\n"
        f"🔔 Уведомления: <b>{status}</b>\n"
        f"📅 Год: <b>{s['min_year']}+</b>\n"
        f"📉 Минимальная скидка: <b>{s['min_discount']:g}%</b>\n"
        f"🔎 Проверка: каждые <b>{settings.check_interval_seconds // 60} мин</b>\n\n"
        "Пока доступны объявления из <b>AUTO.RIA</b>."
    )


async def show_settings(callback: CallbackQuery):
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(settings_text(s), parse_mode="HTML", reply_markup=settings_menu())
    await callback.answer()


@dp.message(CommandStart())
async def start_handler(message: Message):
    if _db:
        await _db.add_subscriber(message.chat.id)
        enabled = await _db.notifications_enabled(message.chat.id)
        s = await _db.get_settings(message.chat.id)
    else:
        enabled, s = True, {'min_year': settings.min_year, 'min_discount': settings.min_market_discount_percent, 'max_mileage_km': None, 'max_price_usd': None}
    await message.answer(menu_text(enabled, s), parse_mode="HTML", reply_markup=main_menu(enabled))


@dp.callback_query(lambda c: c.data == "toggle_notifications")
async def toggle_notifications(callback: CallbackQuery):
    enabled = await _db.toggle_notifications(callback.message.chat.id)
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(menu_text(enabled, s), parse_mode="HTML", reply_markup=main_menu(enabled))
    await callback.answer("Уведомления включены 🔔" if enabled else "Уведомления выключены 🔕")


@dp.callback_query(lambda c: c.data == "settings")
async def settings_handler(callback: CallbackQuery):
    await show_settings(callback)


@dp.callback_query(lambda c: c.data in {"set_year", "set_discount", "set_mileage", "set_price"})
async def setting_choice_handler(callback: CallbackQuery):
    kind = callback.data.removeprefix("set_")
    await callback.message.edit_text(
        "Выбери значение:",
        reply_markup=choices_menu(kind),
    )
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("choose_"))
async def choose_setting_handler(callback: CallbackQuery):
    _, kind, raw = callback.data.split("_", 2)
    field_map = {
        "year": "min_year",
        "discount": "min_discount",
        "mileage": "max_mileage_km",
        "price": "max_price_usd",
    }
    value = None if raw == "none" else float(raw)
    if kind == "year":
        value = int(value)
    elif value is not None and kind in {"mileage", "price"}:
        value = int(value)
    await _db.update_setting(callback.message.chat.id, field_map[kind], value)
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(settings_text(s), parse_mode="HTML", reply_markup=settings_menu())
    await callback.answer("Настройка сохранена ✅")


@dp.callback_query(lambda c: c.data == "back_menu")
async def back_menu_handler(callback: CallbackQuery):
    enabled = await _db.notifications_enabled(callback.message.chat.id)
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(menu_text(enabled, s), parse_mode="HTML", reply_markup=main_menu(enabled))
    await callback.answer()


@dp.message()
async def fallback_handler(message: Message):
    if _db:
        await _db.add_subscriber(message.chat.id)
        enabled = await _db.notifications_enabled(message.chat.id)
        s = await _db.get_settings(message.chat.id)
    else:
        enabled, s = True, {'min_year': settings.min_year, 'min_discount': settings.min_market_discount_percent, 'max_mileage_km': None, 'max_price_usd': None}
    await message.answer(menu_text(enabled, s), parse_mode="HTML", reply_markup=main_menu(enabled))


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
