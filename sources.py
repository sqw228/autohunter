from dataclasses import dataclass
from datetime import datetime, timezone
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
    published_at: str | None = None

class AutoriaSource:
    def __init__(self):
        self.api_key=settings.autoria_api_key
        self.client=httpx.AsyncClient(timeout=20.0)
    async def close(self): await self.client.aclose()
    async def _get(self,url,params):
        r=await self.client.get(url,params=params); r.raise_for_status(); return r.json()

    async def search_ids(self):
        if not self.api_key: return []
        now=datetime.now(timezone.utc)
        after=now.timestamp()-settings.check_interval_seconds-300
        after_iso=datetime.fromtimestamp(after,tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        params=[("api_key",self.api_key),("category_id","1"),("s_yers[0]",str(settings.min_year)),
                ("po_yers[0]",str(now.year)),("currency","1"),("countpage",str(settings.max_listings_per_check)),
                ("page","0"),("with_photo","1"),("published_after",after_iso)]
        try:
            data=await self._get(RIA_SEARCH_URL,params)
        except httpx.HTTPStatusError:
            params=[p for p in params if p[0]!="published_after"]
            data=await self._get(RIA_SEARCH_URL,params)
        try: return [str(x) for x in data[0]["result"]["search_result"]["ids"]][:settings.max_listings_per_check]
        except (KeyError,TypeError,IndexError): return []

    async def get_listing(self,source_id):
        if not self.api_key: return None
        data=await self._get(RIA_INFO_URL,[("api_key",self.api_key),("auto_id",source_id)])
        if not isinstance(data,list) or not data or not isinstance(data[0],dict): return None
        x=data[0]; a=x.get("autoData") or {}; s=x.get("stateData") or {}
        try: mileage=int(float(a.get("raceInt"))*1000) if a.get("raceInt") is not None else None
        except (TypeError,ValueError): mileage=None
        try: year=int(a.get("year")) if a.get("year") is not None else None
        except (TypeError,ValueError): year=None
        try: price=float(x.get("USD")) if x.get("USD") is not None else None
        except (TypeError,ValueError): price=None
        link=x.get("linkToView") or f"/auto_{source_id}.html"
        if link.startswith("/"): link="https://auto.ria.com"+link
        dealer=x.get("dealer") or {}
        return CarListing("AUTO.RIA",source_id,link,x.get("markName"),x.get("modelName"),
                          _as_int(x.get("markId")),_as_int(x.get("modelId")),year=year,mileage_km=mileage,
                          price_usd=price,city=s.get("name") or x.get("locationCityName"),
                          seller_type=dealer.get("type"),title=x.get("title"),description=a.get("description"),
                          published_at=a.get("addDate") or x.get("addDate"))

    async def get_market_median(self,listing):
        if not self.api_key or not listing.brand_id or not listing.model_id: return None
        p=[("api_key",self.api_key),("marka_id",str(listing.brand_id)),("model_id",str(listing.model_id))]
        if listing.year: p += [("yers",str(max(settings.min_year,listing.year-1))),("yers",str(listing.year+1))]
        if listing.mileage_km is not None:
            r=max(0,int(listing.mileage_km/1000)); p += [("raceInt",str(max(0,r-50))),("raceInt",str(r+50))]
        try: data=await self._get(RIA_AVERAGE_URL,p)
        except httpx.HTTPStatusError: return None
        if not isinstance(data,dict): return None
        q=data.get("percentiles") or {}; value=q.get("50.0",q.get(50.0))
        try: return float(value) if value is not None else None
        except (TypeError,ValueError): return None

def _as_int(value):
    try: return int(value) if value is not None else None
    except (TypeError,ValueError): return None

class OlxSource:
    async def search(self): return []
