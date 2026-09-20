from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from config import settings
from database import Database

from sources import AutoriaSource

dp = Dispatcher()
_db = None
_source = None
PAGE_SIZE = 8


def set_database(db):
    global _db
    _db = db


def set_source(source):
    global _source
    _source = source


def main_menu(enabled=True):
    status = "ВКЛ" if enabled else "ВЫКЛ"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🔔 Уведомления: {status}", callback_data="toggle_notifications")],
        [InlineKeyboardButton(text="⚙️ Мои настройки", callback_data="settings")],
    ])


def settings_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚗 Марка", callback_data="set_brand")],
        [InlineKeyboardButton(text="🚘 Модель", callback_data="set_model")],
        [InlineKeyboardButton(text="📍 Регион", callback_data="set_region")],
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


def page_menu(items, prefix, page, back="settings"):
    start = page * PAGE_SIZE
    part = items[start:start + PAGE_SIZE]
    rows = [[InlineKeyboardButton(text=name[:60], callback_data=f"{prefix}_{value}")] for name, value in part]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"page_{prefix}_{page - 1}"))
    if start + PAGE_SIZE < len(items):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"page_{prefix}_{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🚫 Не выбирать", callback_data=f"clear_{prefix}")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data=back)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def settings_text(s):
    mileage = f"{s['max_mileage_km']:,} км".replace(",", " ") if s['max_mileage_km'] else "без ограничения"
    price = f"${s['max_price_usd']:,.0f}".replace(",", " ") if s['max_price_usd'] else "без ограничения"
    brand = s.get('brand_name') or "любая"
    model = s.get('model_name') or "любой"
    region = s.get('region_name') or "вся Украина"
    return (
        "⚙️ <b>Мои настройки</b>\n\n"
        f"🚗 Марка: <b>{brand}</b>\n"
        f"🚘 Модель: <b>{model}</b>\n"
        f"📍 Регион: <b>{region}</b>\n"
        f"📅 Минимальный год: <b>{s['min_year']}+</b>\n"
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
        f"🚗 Марка: <b>{s.get('brand_name') or 'любая'}</b>\n"
        f"🚘 Модель: <b>{s.get('model_name') or 'любая'}</b>\n"
        f"📍 Регион: <b>{s.get('region_name') or 'вся Украина'}</b>\n"
        f"📅 Год: <b>{s['min_year']}+</b>\n"
        f"📉 Минимальная скидка: <b>{s['min_discount']:g}%</b>\n"
        f"🔎 Проверка: каждые <b>{settings.check_interval_seconds // 60} мин</b>\n\n"
        "Источник: <b>AUTO.RIA</b>."
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
        enabled, s = True, {'min_year': settings.min_year, 'min_discount': settings.min_market_discount_percent, 'max_mileage_km': None, 'max_price_usd': None, 'brand_name': None, 'model_name': None, 'region_name': None}
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


@dp.callback_query(lambda c: c.data == "set_brand")
async def set_brand_handler(callback: CallbackQuery):
    await callback.answer("Загружаю марки…")
    try:
        items = await _source.get_marks()
        if not items:
            await callback.message.edit_text(
                "Не удалось получить список марок из AUTO.RIA. Попробуй ещё раз через минуту.",
                reply_markup=settings_menu(),
            )
            return
        await callback.message.edit_text(
            "🚗 <b>Выбери марку</b>:",
            parse_mode="HTML",
            reply_markup=page_menu(items, "brand", 0),
        )
    except Exception:
        await callback.message.edit_text(
            "⚠️ AUTO.RIA не вернул список марок. Проверь логи Railway.",
            reply_markup=settings_menu(),
        )


@dp.callback_query(lambda c: c.data == "set_model")
async def set_model_handler(callback: CallbackQuery):
    s = await _db.get_settings(callback.message.chat.id)
    if not s.get('brand_id'):
        await callback.answer("Сначала выбери марку", show_alert=True)
        return
    await callback.answer("Загружаю модели…")
    try:
        items = await _source.get_models(s['brand_id'])
        if not items:
            await callback.message.edit_text(
                "Не удалось получить список моделей из AUTO.RIA. Попробуй ещё раз через минуту.",
                reply_markup=settings_menu(),
            )
            return
        await callback.message.edit_text(
            "🚘 <b>Выбери модель</b>:",
            parse_mode="HTML",
            reply_markup=page_menu(items, "model", 0),
        )
    except Exception:
        await callback.message.edit_text(
            "⚠️ AUTO.RIA не вернул список моделей. Проверь логи Railway.",
            reply_markup=settings_menu(),
        )


@dp.callback_query(lambda c: c.data == "set_region")
async def set_region_handler(callback: CallbackQuery):
    await callback.answer("Загружаю регионы…")
    try:
        items = await _source.get_states()
        if not items:
            await callback.message.edit_text(
                "Не удалось получить список регионов из AUTO.RIA. Попробуй ещё раз через минуту.",
                reply_markup=settings_menu(),
            )
            return
        await callback.message.edit_text(
            "📍 <b>Выбери регион</b>:",
            parse_mode="HTML",
            reply_markup=page_menu(items, "region", 0),
        )
    except Exception:
        await callback.message.edit_text(
            "⚠️ AUTO.RIA не вернул список регионов. Проверь логи Railway.",
            reply_markup=settings_menu(),
        )


@dp.callback_query(lambda c: c.data.startswith("page_brand_"))
async def page_brand_handler(callback: CallbackQuery):
    page = int(callback.data.rsplit("_", 1)[1])
    await callback.message.edit_reply_markup(reply_markup=page_menu(await _source.get_marks(), "brand", page))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("page_model_"))
async def page_model_handler(callback: CallbackQuery):
    s = await _db.get_settings(callback.message.chat.id)
    if not s.get('brand_id'):
        await callback.answer("Сначала выбери марку", show_alert=True)
        return
    page = int(callback.data.rsplit("_", 1)[1])
    await callback.message.edit_reply_markup(reply_markup=page_menu(await _source.get_models(s['brand_id']), "model", page))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("page_region_"))
async def page_region_handler(callback: CallbackQuery):
    page = int(callback.data.rsplit("_", 1)[1])
    await callback.message.edit_reply_markup(reply_markup=page_menu(await _source.get_states(), "region", page))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("brand_"))
async def choose_brand_handler(callback: CallbackQuery):
    brand_id = int(callback.data.split("_", 1)[1])
    brand = next((x for x in await _source.get_marks() if x[1] == brand_id), None)
    if not brand:
        await callback.answer("Марка не найдена", show_alert=True)
        return
    await _db.set_brand(callback.message.chat.id, brand_id, brand[0])
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(settings_text(s), parse_mode="HTML", reply_markup=settings_menu())
    await callback.answer("Марка сохранена ✅")


@dp.callback_query(lambda c: c.data.startswith("model_"))
async def choose_model_handler(callback: CallbackQuery):
    model_id = int(callback.data.split("_", 1)[1])
    s = await _db.get_settings(callback.message.chat.id)
    models = await _source.get_models(s['brand_id']) if s.get('brand_id') else []
    model = next((x for x in models if x[1] == model_id), None)
    if not model:
        await callback.answer("Модель не найдена", show_alert=True)
        return
    await _db.set_model(callback.message.chat.id, model_id, model[0])
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(settings_text(s), parse_mode="HTML", reply_markup=settings_menu())
    await callback.answer("Модель сохранена ✅")


@dp.callback_query(lambda c: c.data.startswith("region_"))
async def choose_region_handler(callback: CallbackQuery):
    region_id = int(callback.data.split("_", 1)[1])
    region = next((x for x in await _source.get_states() if x[1] == region_id), None)
    if not region:
        await callback.answer("Регион не найден", show_alert=True)
        return
    await _db.set_region(callback.message.chat.id, region_id, region[0])
    s = await _db.get_settings(callback.message.chat.id)
    await callback.message.edit_text(settings_text(s), parse_mode="HTML", reply_markup=settings_menu())
    await callback.answer("Регион сохранён ✅")


@dp.callback_query(lambda c: c.data in {"clear_brand", "clear_model", "clear_region"})
async def clear_catalog_handler(callback: CallbackQuery):
    kind = callback.data.removeprefix("clear_")
    if kind == "brand":
        await _db.set_brand(callback.message.chat.id, None, None)
    elif kind == "model":
        await _db.set_model(callback.message.chat.id, None, None)
    else:
        await _db.set_region(callback.message.chat.id, None, None)
    await show_settings(callback)
    await callback.answer("Фильтр сброшен")


@dp.callback_query(lambda c: c.data in {"set_year", "set_discount", "set_mileage", "set_price"})
async def setting_choice_handler(callback: CallbackQuery):
    kind = callback.data.removeprefix("set_")
    await callback.message.edit_text("Выбери значение:", reply_markup=choices_menu(kind))
    await callback.answer()


@dp.callback_query(lambda c: c.data.startswith("choose_"))
async def choose_setting_handler(callback: CallbackQuery):
    _, kind, raw = callback.data.split("_", 2)
    field_map = {"year": "min_year", "discount": "min_discount", "mileage": "max_mileage_km", "price": "max_price_usd"}
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
        enabled, s = True, {'min_year': settings.min_year, 'min_discount': settings.min_market_discount_percent, 'max_mileage_km': None, 'max_price_usd': None, 'brand_name': None, 'model_name': None, 'region_name': None}
    await message.answer(menu_text(enabled, s), parse_mode="HTML", reply_markup=main_menu(enabled))


async def run_bot():
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured")
    import asyncio
    from scanner import scanner_loop
    db = Database(settings.database_url)
    await db.connect()
    set_database(db)
    source = AutoriaSource()
    set_source(source)
    bot = Bot(token=settings.telegram_bot_token)
    task = asyncio.create_task(scanner_loop(bot, db, source))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        await source.close()
        await bot.session.close()
        await db.close()
