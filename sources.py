from dataclasses import dataclass
from datetime import datetime
import asyncio
import httpx
from config import settings

RIA_SEARCH_URL = "https://developers.ria.com/auto/search"
RIA_INFO_URL = "https://developers.ria.com/auto/info"
RIA_AVERAGE_URL = "https://developers.ria.com/auto/average_price"


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


class AutoriaSource:
    def __init__(self):
        self.api_key = settings.autoria_api_key
        self.client = httpx.AsyncClient(timeout=20.0)
        self.retry_after_until = 0.0
        self.page = 0
        self.request_times = []
        self.max_requests_per_hour = 25

    async def close(self):
        await self.client.aclose()

    async def _wait_for_local_limit(self):
        loop = asyncio.get_running_loop()
        now = loop.time()

        self.request_times = [
            t for t in self.request_times
            if now - t < 3600
        ]

        if len(self.request_times) >= self.max_requests_per_hour:
            oldest = min(self.request_times)
            wait = 3600 - (now - oldest)
            raise RuntimeError(
                f"local AUTO.RIA hourly limit reached; wait {int(wait)} seconds"
            )

    async def _get(self, url, params):
        loop = asyncio.get_running_loop()

        wait = self.retry_after_until - loop.time()
        if wait > 0:
            raise RuntimeError(
                f"AUTO.RIA rate-limit cooldown active; wait {int(wait)} seconds"
            )

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

            raise RuntimeError(
                f"AUTO.RIA API returned HTTP 429; cooldown {cooldown} seconds"
            )

        r.raise_for_status()

        data = r.json()

        safe_raw = repr(data)
        if self.api_key:
            safe_raw = safe_raw.replace(self.api_key, "***")
        print(f"AUTO.RIA response: status={r.status_code}, type={type(data).__name__}")
        print(f"AUTO.RIA response preview: {safe_raw[:2000]}")

        return data

    async def search_ids(self):
        if not self.api_key:
            return []

        now = datetime.now().astimezone()
        current_page = self.page

        params = [
            ("api_key", self.api_key),
            ("category_id", "1"),
            ("s_yers[0]", str(settings.min_year)),
            ("po_yers[0]", str(now.year)),
            ("currency", "1"),
            ("countpage", str(settings.max_listings_per_check)),
            ("page", str(current_page)),
            ("with_photo", "1"),
        ]

        print(
            f"AUTO.RIA search: page={current_page}, "
            f"year={settings.min_year}-{now.year}"
        )

        data = await self._get(RIA_SEARCH_URL, params)

        if isinstance(data, list):
            print(f"AUTO.RIA search response: list length={len(data)}")
            if data and isinstance(data[0], dict):
                print("AUTO.RIA search response keys:", list(data[0].keys()))
                result = data[0].get("result")
                if isinstance(result, dict):
                    print("AUTO.RIA result keys:", list(result.keys()))
                    search_result = result.get("search_result")
                    if isinstance(search_result, dict):
                        print(
                            "AUTO.RIA search_result keys:",
                            list(search_result.keys())
                        )

                ids = (
                    data[0].get("result", {})
                    .get("search_result", {})
                    .get("ids", [])
                )
                if isinstance(ids, list):
                    result_ids = [
                        str(x) for x in ids if x is not None
                    ][:settings.max_listings_per_check]
                    if result_ids:
                        print(f"AUTO.RIA parsed listing IDs: {result_ids}")
                        return result_ids

        if isinstance(data, dict):
            print("AUTO.RIA top-level dict keys:", list(data.keys()))

            ids = data.get("ids")
            if isinstance(ids, list):
                result_ids = [
                    str(x) for x in ids if x is not None
                ][:settings.max_listings_per_check]
                if result_ids:
                    print(f"AUTO.RIA parsed IDs from dict: {result_ids}")
                    return result_ids

            result = data.get("result")
            if isinstance(result, dict):
                search_result = result.get("search_result")
                if isinstance(search_result, dict):
                    ids = search_result.get("ids")
                    if isinstance(ids, list):
                        result_ids = [
                            str(x) for x in ids if x is not None
                        ][:settings.max_listings_per_check]
                        if result_ids:
                            print(
                                f"AUTO.RIA parsed IDs from result.search_result: "
                                f"{result_ids}"
                            )
                            return result_ids

        print("AUTO.RIA: could not find listing IDs in search response")
        return []

    async def get_listing(self, source_id):
        if not self.api_key:
            return None

        data = await self._get(
            RIA_INFO_URL,
            [
                ("api_key", self.api_key),
                ("auto_id", source_id),
            ],
        )

        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            return None

        x = data[0]
        a = x.get("autoData") or {}
        s = x.get("stateData") or {}

        try:
            mileage = (
                int(float(a.get("raceInt")) * 1000)
                if a.get("raceInt") is not None else None
            )
        except (TypeError, ValueError):
            mileage = None

        try:
            year = int(a.get("year")) if a.get("year") is not None else None
        except (TypeError, ValueError):
            year = None

        try:
            price = float(x.get("USD")) if x.get("USD") is not None else None
        except (TypeError, ValueError):
            price = None

        link = x.get("linkToView") or f"/auto_{source_id}.html"
        if link.startswith("/"):
            link = "https://auto.ria.com" + link

        dealer = x.get("dealer") or {}

        return CarListing(
            source="AUTO.RIA",
            source_id=source_id,
            url=link,
            brand=x.get("markName"),
            model=x.get("modelName"),
            brand_id=_as_int(x.get("markId")),
            model_id=_as_int(x.get("modelId")),
            year=year,
            mileage_km=mileage,
            price_usd=price,
            city=s.get("name") or x.get("locationCityName"),
            seller_type=dealer.get("type"),
            title=x.get("title"),
            description=a.get("description"),
            published_at=_parse_date(
                a.get("addDate") or x.get("addDate")
            ),
        )

    async def get_market_median(self, listing):
        if not self.api_key or not listing.brand_id or not listing.model_id:
            return None

        params = [
            ("api_key", self.api_key),
            ("marka_id", str(listing.brand_id)),
            ("model_id", str(listing.model_id)),
        ]

        if listing.year:
            params += [
                ("yers", str(max(settings.min_year, listing.year - 1))),
                ("yers", str(listing.year + 1)),
            ]

        if listing.mileage_km is not None:
            race = max(0, int(listing.mileage_km / 1000))
            params += [
                ("raceInt", str(max(0, race - 50))),
                ("raceInt", str(race + 50)),
            ]

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
