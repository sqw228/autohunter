from dataclasses import dataclass
from datetime import datetime
import asyncio
import httpx
from config import settings

RIA_SEARCH_URL = "https://developers.ria.com/auto/search"
RIA_INFO_URL = "https://developers.ria.com/auto/info"
RIA_AVERAGE_URL = "https://developers.ria.com/auto/average_price"
RIA_MARKS_URL = "https://developers.ria.com/auto/categories/1/marks"
RIA_STATES_URL = "https://developers.ria.com/auto/states"


@dataclass(slots=True)
class CarListing:
    source: str
    source_id: str
    url: str
    brand: str | None = None
    model: str | None = None
    brand_id: int | None = None
    model_id: int | None = None
    generation: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    price_usd: float | None = None
    city: str | None = None
    region_id: int | None = None
    seller_type: str | None = None
    title: str | None = None
    description: str | None = None
    published_at: datetime | None = None


class AutoriaSource:
    def __init__(self, db=None):
        self.api_key = settings.autoria_api_key
        self.db = db
        self.client = httpx.AsyncClient(timeout=20.0)
        self.retry_after_until = 0.0
        self.page = 0
        self.request_times = []
        self.max_requests_per_hour = 25
        self._marks_cache = None
        self._models_cache = {}
        self._states_cache = None

    async def close(self):
        await self.client.aclose()

    async def _wait_for_local_limit(self):
        loop = asyncio.get_running_loop()
        now = loop.time()
        self.request_times = [t for t in self.request_times if now - t < 3600]
        if len(self.request_times) >= self.max_requests_per_hour:
            oldest = min(self.request_times)
            wait = 3600 - (now - oldest)
            raise RuntimeError(f"local AUTO.RIA hourly limit reached; wait {int(wait)} seconds")

    async def _get(self, url, params):
        loop = asyncio.get_running_loop()
        wait = self.retry_after_until - loop.time()
        if wait > 0:
            raise RuntimeError(f"AUTO.RIA rate-limit cooldown active; wait {int(wait)} seconds")
        await self._wait_for_local_limit()
        r = await self.client.get(url, params=params)
        self.request_times.append(loop.time())
        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            try:
                cooldown = int(retry_after)
            except (TypeError, ValueError):
                cooldown = settings.autoria_retry_after_seconds
            self.retry_after_until = loop.time() + cooldown
            raise RuntimeError(f"AUTO.RIA API returned HTTP 429; cooldown {cooldown} seconds")
        r.raise_for_status()
        data = r.json()
        safe_raw = repr(data)
        if self.api_key:
            safe_raw = safe_raw.replace(self.api_key, "***")
        print(f"AUTO.RIA response: status={r.status_code}, type={type(data).__name__}")
        print(f"AUTO.RIA response preview: {safe_raw[:2000]}")
        return data

    async def _get_catalog(self, url, params):
        return await self._get(url, params)

    @staticmethod
    def _catalog_items(data):
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("result") or data.get("items") or data.get("data") or []
            if isinstance(items, dict):
                items = items.get("items") or items.get("result") or items.get("data") or []
        else:
            items = []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("title") or item.get("name_ru") or item.get("name_uk")
            value = (
                item.get("value")
                or item.get("id")
                or item.get("marka_id")
                or item.get("model_id")
                or item.get("state_id")
            )
            if name and value is not None:
                try:
                    out.append((str(name), int(value)))
                except (TypeError, ValueError):
                    continue
        return out

    async def get_marks(self):
        if self._marks_cache is not None:
            return self._marks_cache
        if self.db:
            cached = await self.db.get_catalog_cache("brand", 0)
            if cached:
                self._marks_cache = cached
                return cached
        if not self.api_key or self.retry_after_until > asyncio.get_running_loop().time():
            return []
        try:
            data = await self._get_catalog(RIA_MARKS_URL, [("api_key", self.api_key)])
            items = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
            if items:
                self._marks_cache = items
                if self.db:
                    await self.db.set_catalog_cache("brand", 0, items)
            return items
        except Exception as e:
            print(f"AUTO.RIA marks unavailable: {e}")
            return await self.db.get_catalog_cache("brand", 0) if self.db else []

    async def get_models(self, brand_id):
        brand_id = int(brand_id)
        if brand_id in self._models_cache:
            return self._models_cache[brand_id]
        if self.db:
            cached = await self.db.get_catalog_cache("model", brand_id)
            if cached:
                self._models_cache[brand_id] = cached
                return cached
        if not self.api_key or self.retry_after_until > asyncio.get_running_loop().time():
            return []
        try:
            url = f"https://developers.ria.com/auto/categories/1/marks/{brand_id}/models"
            data = await self._get_catalog(url, [("api_key", self.api_key)])
            models = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
            self._models_cache[brand_id] = models
            if self.db and models:
                await self.db.set_catalog_cache("model", brand_id, models)
            return models
        except Exception as e:
            print(f"AUTO.RIA models unavailable: {e}")
            return await self.db.get_catalog_cache("model", brand_id) if self.db else []

    async def get_states(self):
        if self._states_cache is not None:
            return self._states_cache
        if self.db:
            cached = await self.db.get_catalog_cache("state", 0)
            if cached:
                self._states_cache = cached
                return cached
        if not self.api_key or self.retry_after_until > asyncio.get_running_loop().time():
            return []
        try:
            data = await self._get_catalog(RIA_STATES_URL, [("api_key", self.api_key)])
            items = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
            self._states_cache = items
            if self.db and items:
                await self.db.set_catalog_cache("state", 0, items)
            return items
        except Exception as e:
            print(f"AUTO.RIA states unavailable: {e}")
            return await self.db.get_catalog_cache("state", 0) if self.db else []

    async def search_ids(self, user_settings=None):
        if not self.api_key:
            return []

        now = datetime.now().astimezone()
        current_page = self.page
        params = [
            ("api_key", self.api_key),
            ("category_id", "1"),
            ("s_yers[0]", str(user_settings['min_year'] if user_settings else settings.min_year)),
            ("po_yers[0]", str(now.year)),
            ("currency", "1"),
            ("countpage", str(settings.max_listings_per_check)),
            ("page", str(current_page)),
            ("with_photo", "1"),
        ]

        if user_settings:
            if user_settings.get('brand_id'):
                params.append(("marka_id[0]", str(user_settings['brand_id'])))
                params.append(("model_id[0]", str(user_settings.get('model_id') or 0)))
            if user_settings.get('region_id'):
                params.append(("state[0]", str(user_settings['region_id'])))
                params.append(("city[0]", "0"))

        print(
            f"AUTO.RIA search: page={current_page}, "
            f"year={user_settings['min_year'] if user_settings else settings.min_year}-{now.year}, "
            f"brand={user_settings.get('brand_id') if user_settings else None}, "
            f"model={user_settings.get('model_id') if user_settings else None}, "
            f"region={user_settings.get('region_id') if user_settings else None}"
        )

        try:
            data = await self._get(RIA_SEARCH_URL, params)
        except RuntimeError as e:
            print(f"AUTO.RIA search skipped: {e}")
            return []

        if isinstance(data, list):
            ids = data[0].get("result", {}).get("search_result", {}).get("ids", []) if data and isinstance(data[0], dict) else []
            if isinstance(ids, list) and ids:
                result_ids = [str(x) for x in ids if x is not None][:settings.max_listings_per_check]
                print(f"AUTO.RIA parsed listing IDs: {result_ids}")
                return result_ids

        if isinstance(data, dict):
            result = data.get("result") or {}
            search_result = result.get("search_result") or {}
            ids = search_result.get("ids")
            if isinstance(ids, list):
                result_ids = [str(x) for x in ids if x is not None][:settings.max_listings_per_check]
                if result_ids:
                    print(f"AUTO.RIA parsed IDs from result.search_result: {result_ids}")
                    return result_ids
            ids = data.get("ids")
            if isinstance(ids, list):
                result_ids = [str(x) for x in ids if x is not None][:settings.max_listings_per_check]
                if result_ids:
                    print(f"AUTO.RIA parsed IDs from dict: {result_ids}")
                    return result_ids

        print("AUTO.RIA: could not find listing IDs in search response")
        return []

    async def get_listing(self, source_id):
        if not self.api_key:
            return None
        data = await self._get(RIA_INFO_URL, [("api_key", self.api_key), ("auto_id", source_id)])
        if isinstance(data, list):
            if not data or not isinstance(data[0], dict):
                return None
            x = data[0]
        elif isinstance(data, dict):
            x = data
        else:
            return None

        a = x.get("autoData") or {}
        s = x.get("stateData") or {}

        def first_value(*values):
            for value in values:
                if value is not None and value != "":
                    return value
            return None

        raw_mileage = first_value(x.get("raceInt"), x.get("mileage"), a.get("raceInt"), a.get("mileage"))
        try:
            mileage = int(float(raw_mileage) * 1000) if raw_mileage is not None else None
        except (TypeError, ValueError):
            mileage = None

        raw_year = first_value(x.get("year"), a.get("year"))
        try:
            year = int(raw_year) if raw_year is not None else None
        except (TypeError, ValueError):
            year = None

        raw_price = x.get("USD")
        if raw_price is None:
            prices = x.get("prices") or []
            if prices and isinstance(prices[0], dict):
                raw_price = prices[0].get("USD")
        try:
            price = float(str(raw_price).replace(" ", "")) if raw_price is not None else None
        except (TypeError, ValueError):
            price = None

        link = x.get("linkToView") or f"/auto_{source_id}.html"
        if link.startswith("/"):
            link = "https://auto.ria.com" + link
        dealer = x.get("dealer") or {}

        return CarListing(
            source="AUTO.RIA", source_id=source_id, url=link,
            brand=first_value(x.get("markName"), x.get("markNameEng")),
            model=x.get("modelName"),
            brand_id=_as_int(first_value(x.get("markId"), x.get("mark_id"))),
            model_id=_as_int(first_value(x.get("modelId"), x.get("model_id"))),
            year=year, mileage_km=mileage, price_usd=price,
            city=first_value(s.get("name"), x.get("locationCityName")),
            region_id=_as_int(first_value(s.get("id"), s.get("stateId"), x.get("stateId"))),
            seller_type=dealer.get("type"), title=x.get("title"),
            description=first_value(x.get("description"), a.get("description")),
            published_at=_parse_date(x.get("addDate") or a.get("addDate")),
        )

    async def get_market_median(self, listing):
        if not self.api_key or not listing.brand_id or not listing.model_id:
            return None
        params = [("api_key", self.api_key), ("marka_id", str(listing.brand_id)), ("model_id", str(listing.model_id))]
        if listing.year:
            params += [("yers", str(max(settings.min_year, listing.year - 1))), ("yers", str(listing.year + 1))]
        if listing.mileage_km is not None:
            race = max(0, int(listing.mileage_km / 1000))
            params += [("raceInt", str(max(0, race - 50))), ("raceInt", str(race + 50))]
        try:
            data = await self._get(RIA_AVERAGE_URL, params)
        except (RuntimeError, httpx.HTTPStatusError):
            return None
        if not isinstance(data, dict):
            return None
        percentiles = data.get("percentiles") or {}
        value = percentiles.get("50.0", percentiles.get(50.0))
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None


class OlxSource:
    async def search(self):
        return []


def _as_int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _parse_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except (TypeError, ValueError):
            pass
    return None
