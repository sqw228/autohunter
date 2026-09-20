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
    seller_type: str | None = None
    title: str | None = None
    description: str | None = None
    published_at: datetime | None = None
    transmission: str | None = None
    fuel: str | None = None


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
        await asyncio.sleep(2)
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
        return data

    async def _get_catalog(self, url, params):
        return await self._get(url, params)

    @staticmethod
    def _catalog_items(data):
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("result") or data.get("items") or data.get("data") or []
        else:
            items = []
        out = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = item.get("name") or item.get("title")
            value = item.get("value") or item.get("marka_id") or item.get("model_id")
            if name and value is not None:
                out.append((str(name), int(value)))
        return out

    async def get_marks(self):
        if self._marks_cache is not None:
            return self._marks_cache
        if not self.api_key:
            return []
        data = await self._get_catalog(RIA_MARKS_URL, [("api_key", self.api_key)])
        self._marks_cache = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
        return self._marks_cache

    async def get_models(self, brand_id):
        if brand_id in self._models_cache:
            return self._models_cache[brand_id]
        if not self.api_key:
            return []
        url = f"https://developers.ria.com/auto/categories/1/marks/{brand_id}/models"
        data = await self._get_catalog(url, [("api_key", self.api_key)])
        models = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
        self._models_cache[brand_id] = models
        return models

    async def get_states(self):
        if self._states_cache is not None:
            return self._states_cache
        if not self.api_key:
            return []
        data = await self._get_catalog(RIA_STATES_URL, [("api_key", self.api_key)])
        self._states_cache = sorted(self._catalog_items(data), key=lambda x: x[0].lower())
        return self._states_cache

    async def find_catalog(self, kind, query, parent_id=0):
        query = (query or "").strip().lower()
        if kind == "brand":
            items = await self.get_marks()
        elif kind == "model":
            items = await self.get_models(parent_id)
        elif kind == "region":
            items = await self.get_states()
        else:
            return []
        return [item for item in items if query in item[0].lower()]


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
                if user_settings.get('model_id'):
                    params.append(("model_id[0]", str(user_settings['model_id'])))
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

        data = await self._get(RIA_SEARCH_URL, params)

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
        def text_value(value):
            if isinstance(value, dict):
                return first_value(value.get("name"), value.get("title"), value.get("value"))
            return value
        transmission = text_value(first_value(x.get("gearboxName"), x.get("gearbox"), a.get("gearboxName"), a.get("gearbox")))
        fuel = text_value(first_value(x.get("fuelName"), x.get("fuel"), a.get("fuelName"), a.get("fuel")))

        return CarListing(
            source="AUTO.RIA", source_id=source_id, url=link,
            brand=first_value(x.get("markName"), x.get("markNameEng")),
            model=x.get("modelName"),
            brand_id=_as_int(first_value(x.get("markId"), x.get("mark_id"))),
            model_id=_as_int(first_value(x.get("modelId"), x.get("model_id"))),
            year=year, mileage_km=mileage, price_usd=price,
            city=first_value(s.get("name"), x.get("locationCityName")),
            seller_type=dealer.get("type"), title=x.get("title"),
            description=first_value(x.get("description"), a.get("description")),
            transmission=str(transmission) if transmission else None,
            fuel=str(fuel) if fuel else None,
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
