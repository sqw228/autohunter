import asyncio
import logging
from aiogram import Bot
from config import settings
from database import Database
from sources import AutoriaSource, CarListing

log=logging.getLogger(__name__)

def fmt(x:CarListing,median:float):
    discount=(1-x.price_usd/median)*100
    return "\n".join(["🔥 <b>МАШИНА НИЖЕ РЫНКА</b>","",f"🚗 <b>{x.brand or ''} {x.model or ''}</b>",f"📅 {x.year or '—'}",f"🛣 {x.mileage_km:,} км".replace(","," ") if x.mileage_km else "🛣 —",f"💰 <b>{x.price_usd:,.0f} USD</b>".replace(","," "),f"📊 Рынок: ~<b>{median:,.0f} USD</b>".replace(","," "),f"📉 Ниже рынка: <b>{discount:.1f}%</b>",f"📍 {x.city or 'Украина'}","",f'<a href="{x.url}">Открыть объявление</a>'])

async def scanner_loop(bot:Bot,db:Database):
    source=AutoriaSource()
    try:
        while True:
            try:
                for sid in await source.search_ids():
                    try:
                        x=await source.get_listing(sid)
                        if not x or not x.year or x.year<settings.min_year or not x.price_usd or x.price_usd<=0: continue
                        if not await db.save_listing(x): continue
                        key=f"ria:{x.brand_id}:{x.model_id}:{x.year}"
                        median=await db.get_market_cache(key,settings.market_cache_hours)
                        if median is None:
                            median=await source.get_market_median(x)
                            if median: await db.set_market_cache(key,median)
                        if not median or (1-x.price_usd/median)*100<settings.min_market_discount_percent: continue
                        for chat_id in await db.subscribers():
                            try: await bot.send_message(chat_id,fmt(x,median),parse_mode="HTML")
                            except Exception: log.exception("notify failed")
                    except Exception: log.exception("listing failed: %s",sid)
            except Exception: log.exception("scan failed")
            await asyncio.sleep(settings.check_interval_seconds)
    finally: await source.close()
