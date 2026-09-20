import asyncio
import logging

from bot import run_bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


if __name__ == "__main__":
    asyncio.run(run_bot())
