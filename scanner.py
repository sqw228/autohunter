import asyncio
import logging
from aiogram import Bot
from config import settings
from database import Database
from sources import AutoriaSource, CarListing

log = logging.getLogger(__name__)


def fmt(x: CarListing, median: float):
    discount = (1 - x.price_usd / median) * 100
    return "\n".join([
        "🔥 <b>МАШИНА НИЖЕ РЫНКА</b>", "",
        f"🚗 <b>{x.brand or ''} {x.model or ''}</b>",
        f"📅 {x.year or '—'}",
        f"🛣 {x.mileage_km:,} км".replace(",", " ") if x.mileage_km else "🛣 —",
        f"💰 <b>{x.price_usd:,.0f} USD</b>".replace(",", " "),
        f"📊 Рынок: ~<b>{median:,.0f} USD</b>".replace(",", " "),
        f"📉 Ниже рынка: <b>{discount:.1f}%</b>",
        f"📍 {x.city or 'Украина'}", "",
        f'<a href="{x.url}">Открыть объявление</a>'
    ])


async def scanner_loop(bot: Bot, db: Database):
    source = AutoriaSource()
    log.info(
        "AutoHunter scanner started: interval=%ss, max=%s",
        settings.check_interval_seconds, settings.max_listings_per_check
    )

    try:
        while True:
            try:
                log.info("Starting AUTO.RIA market scan...")
                try:
                    ids = await source.search_ids()
                except RuntimeError as e:
                    log.warning("AUTO.RIA request skipped/limited: %s", e)
                    ids = []
                except Exception:
                    log.exception("AUTO.RIA search failed")
                    ids = []

                log.info("AUTO.RIA market search returned %s listing IDs", len(ids))

                for sid in ids:
                    try:
                        log.info("Checking listing %s", sid)
                        x = await source.get_listing(sid)

                        if not x:
                            log.warning("Listing %s: info response was empty/unusable", sid)
                            continue

                        log.info(
                            "Listing %s: %s %s, year=%s, price=%s USD, mileage=%s km",
                            sid, x.brand or "", x.model or "", x.year,
                            x.price_usd, x.mileage_km
                        )

                        # The global AUTO.RIA search stays at 2012+ to give all users
                        # a common discovery pool. Individual year/price/mileage filters
                        # are applied per subscriber below.
                        if not x.year or not x.price_usd or x.price_usd <= 0:
                            log.info("Listing %s rejected: missing year/price", sid)
                            continue

                        await db.save_listing(x)

                        key = f"ria:{x.brand_id}:{x.model_id}:{x.year}"
                        median = await db.get_market_cache(key, settings.market_cache_hours)

                        if median is None:
                            log.info("Getting market median for %s", key)
                            median = await source.get_market_median(x)
                            if median:
                                await db.set_market_cache(key, median)

                        if not median:
                            log.warning("Listing %s rejected: market median unavailable", sid)
                            continue

                        discount = (1 - x.price_usd / median) * 100
                        users = await db.subscriber_settings()
                        log.info("Listing %s: market median=%s USD, discount=%.1f%%, users=%s", sid, median, discount, len(users))

                        for user in users:
                            chat_id = user['chat_id']

                            if x.year < user['min_year']:
                                log.info("Listing %s -> user %s rejected: year %s < %s", sid, chat_id, x.year, user['min_year'])
                                continue

                            if discount < user['min_discount']:
                                log.info("Listing %s -> user %s rejected: discount %.1f%% < %.1f%%", sid, chat_id, discount, user['min_discount'])
                                continue

                            if user['max_mileage_km'] is not None and (
                                x.mileage_km is None or x.mileage_km > user['max_mileage_km']
                            ):
                                log.info("Listing %s -> user %s rejected: mileage %s > %s", sid, chat_id, x.mileage_km, user['max_mileage_km'])
                                continue

                            if user['max_price_usd'] is not None and x.price_usd > user['max_price_usd']:
                                log.info("Listing %s -> user %s rejected: price %.0f > %.0f", sid, chat_id, x.price_usd, user['max_price_usd'])
                                continue

                            if await db.was_notified(chat_id, x.source, x.source_id):
                                log.info("Listing %s -> user %s skipped: already sent", sid, chat_id)
                                continue

                            try:
                                await bot.send_message(chat_id, fmt(x, median), parse_mode="HTML")
                                await db.mark_user_notified(chat_id, x.source, x.source_id)
                                log.info("Telegram notification sent: listing=%s chat_id=%s", sid, chat_id)
                            except Exception:
                                log.exception("notify failed for chat_id=%s", chat_id)

                    except Exception:
                        log.exception("listing failed: %s", sid)

            except Exception:
                log.exception("scan failed")

            log.info(
                "Market scan finished; sleeping %s seconds before next page",
                settings.check_interval_seconds
            )
            await asyncio.sleep(settings.check_interval_seconds)

    finally:
        await source.close()
