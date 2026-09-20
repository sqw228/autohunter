import asyncio
import logging
import os

from bot import run_bot
from config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


async def run_web():
    if not settings.webapp_url:
        logging.getLogger(__name__).warning("WEBAPP_URL is not configured; Mini App server is disabled")
        return

    import uvicorn
    from bot import _db, _source
    from webapp import create_app

    app = create_app(_db, _source, settings.telegram_bot_token)
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        log_level="info",
    )
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    web_task = asyncio.create_task(run_web())
    try:
        await run_bot()
    finally:
        web_task.cancel()
        try:
            await web_task
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    asyncio.run(main())
