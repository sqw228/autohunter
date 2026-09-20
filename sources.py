from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class CarListing:
    source: str
    source_id: str
    url: str
    brand: str | None = None
    model: str | None = None
    generation: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    price_usd: float | None = None
    city: str | None = None
    seller_type: str | None = None
    title: str | None = None
    description: str | None = None


class ListingSource(Protocol):
    async def search(self) -> list[CarListing]:
        ...


class AutoriaSource:
    """
    AUTO.RIA adapter.

    The API-specific request/response mapping will be implemented after
    we confirm the exact API endpoints and permissions available for the
    user's API key. Secrets are read only from environment variables.
    """

    async def search(self) -> list[CarListing]:
        return []


class OlxSource:
    """
    OLX adapter placeholder.

    We will implement the compliant data-collection method after checking
    the current access options and restrictions.
    """

    async def search(self) -> list[CarListing]:
        return []
