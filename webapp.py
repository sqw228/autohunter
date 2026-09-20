import hashlib
import hmac
import json
from pathlib import Path
from urllib.parse import parse_qsl

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

WEB_DIR = Path(__file__).parent / "webapp"


def create_app(db, source, bot_token):
    app = FastAPI(title="AutoHunter Mini App")

    def validate_init_data(init_data: str):
        if not init_data:
            raise HTTPException(status_code=401, detail="Missing Telegram init data")

        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise HTTPException(status_code=401, detail="Invalid Telegram init data")

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(pairs.items())
        )
        secret_key = hmac.new(
            b"WebAppData", bot_token.encode(), hashlib.sha256
        ).digest()
        calculated_hash = hmac.new(
            secret_key, data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            raise HTTPException(status_code=401, detail="Invalid Telegram init data")

        try:
            user = json.loads(pairs.get("user", "{}"))
        except json.JSONDecodeError:
            raise HTTPException(status_code=401, detail="Invalid Telegram user")

        if not user.get("id"):
            raise HTTPException(status_code=401, detail="Telegram user not found")
        return int(user["id"])

    def chat_id_from_request(request: Request):
        init_data = request.headers.get("X-Telegram-Init-Data", "")
        return validate_init_data(init_data)

    class SettingsUpdate(BaseModel):
        min_year: int | None = None
        min_discount: float | None = None
        max_mileage_km: int | None = None
        max_price_usd: float | None = None
        brand_id: int | None = None
        brand_name: str | None = None
        model_id: int | None = None
        model_name: str | None = None
        region_id: int | None = None
        region_name: str | None = None

    @app.get("/")
    async def index():
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/api/me")
    async def me(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        return await db.get_settings(chat_id)

    @app.post("/api/settings")
    async def update_settings(payload: SettingsUpdate, request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)

        data = payload.model_dump(exclude_unset=True)

        if "brand_id" in data or "brand_name" in data:
            await db.set_brand(chat_id, data.get("brand_id"), data.get("brand_name"))
            data.pop("brand_id", None)
            data.pop("brand_name", None)
            data.pop("model_id", None)
            data.pop("model_name", None)

        if "model_id" in data or "model_name" in data:
            await db.set_model(chat_id, data.get("model_id"), data.get("model_name"))
            data.pop("model_id", None)
            data.pop("model_name", None)

        if "region_id" in data or "region_name" in data:
            await db.set_region(chat_id, data.get("region_id"), data.get("region_name"))
            data.pop("region_id", None)
            data.pop("region_name", None)

        for field in ("min_year", "min_discount", "max_mileage_km", "max_price_usd"):
            if field in data:
                await db.update_setting(chat_id, field, data[field])

        return await db.get_settings(chat_id)

    @app.get("/api/listings")
    async def listings(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        return await db.get_listings_for_user(chat_id)

    @app.get("/api/favorites")
    async def favorites(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        return await db.get_favorites(chat_id)

    @app.post("/api/favorites")
    async def favorite(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        body = await request.json()
        await db.set_favorite(chat_id, str(body.get("source")), str(body.get("source_id")), bool(body.get("value")))
        return {"ok": True}

    @app.get("/api/stats")
    async def stats(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        return await db.get_stats(chat_id)

    @app.get("/api/language")
    async def language(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        return {"language": await db.get_language(chat_id)}

    @app.post("/api/language")
    async def set_language(request: Request):
        chat_id = chat_id_from_request(request)
        await db.add_subscriber(chat_id)
        body = await request.json()
        lang = body.get("language", "ru")
        await db.set_language(chat_id, lang)
        return {"language": lang}

    @app.get("/api/catalog/brands")
    async def brands(request: Request):
        chat_id_from_request(request)
        return [{"id": value, "name": name} for name, value in await source.get_marks()]

    @app.get("/api/catalog/brands/{brand_id}/models")
    async def models(brand_id: int, request: Request):
        chat_id_from_request(request)
        return [{"id": value, "name": name} for name, value in await source.get_models(brand_id)]

    @app.get("/api/catalog/regions")
    async def regions(request: Request):
        chat_id_from_request(request)
        return [{"id": value, "name": name} for name, value in await source.get_states()]

    return app
