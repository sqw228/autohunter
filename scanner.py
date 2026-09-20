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
        "AutoHunter scanner started: year >= %s, discount >= %s%%, interval=%ss, max=%s",
        settings.min_year, settings.min_market_discount_percent,
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

                        if (
                            not x.year
                            or x.year < settings.min_year
                            or not x.price_usd
                            or x.price_usd <= 0
                        ):
                            log.info(
                                "Listing %s rejected: basic filters "
                                "(year/price)",
                                sid
                            )
                            continue

                        inserted, already_notified = await db.save_listing(x)

                        if already_notified:
                            log.info(
                                "Listing %s skipped: already notified",
                                sid
                            )
                            continue

                        key = f"ria:{x.brand_id}:{x.model_id}:{x.year}"
                        median = await db.get_market_cache(
                            key,
                            settings.market_cache_hours
                        )

                        if median is None:
                            log.info(
                                "Getting market median for %s",
                                key
                            )
                            median = await source.get_market_median(x)

                            if median:
                                await db.set_market_cache(key, median)

                        if not median:
                            log.warning(
                                "Listing %s rejected: market median unavailable",
                                sid
                            )
                            continue

                        discount = (1 - x.price_usd / median) * 100

                        log.info(
                            "Listing %s: market median=%s USD, "
                            "discount=%.1f%%, required=%.1f%%",
                            sid,
                            median,
                            discount,
                            settings.min_market_discount_percent
                        )

                        if discount < settings.min_market_discount_percent:
                            log.info(
                                "Listing %s rejected: discount %.1f%% "
                                "is below required %.1f%%",
                                sid,
                                discount,
                                settings.min_market_discount_percent
                            )
                            continue

                        subscribers = await db.subscribers()
                        log.info(
                            "Listing %s QUALIFIES: notifying %s subscribers",
                            sid,
                            len(subscribers)
                        )

                        if not subscribers:
                            log.warning(
                                "Listing %s qualifies, but there are no "
                                "Telegram subscribers. Send /start in the bot.",
                                sid
                            )
                            continue

                        for chat_id in subscribers:
                            try:
                                await bot.send_message(
                                    chat_id,
                                    fmt(x, median),
                                    parse_mode="HTML"
                                )
                                log.info(
                                    "Telegram notification sent: listing=%s chat_id=%s",
                                    sid,
                                    chat_id
                                )
                            except Exception:
                                log.exception(
                                    "notify failed for chat_id=%s",
                                    chat_id
                                )

                        await db.mark_notified(x.source, x.source_id)

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
