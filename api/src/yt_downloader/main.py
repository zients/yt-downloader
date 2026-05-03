import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI

from yt_downloader.background import cancel_background_tasks, ensure_background_tasks
from yt_downloader.config import settings
from yt_downloader.redis_client import close_redis, get_redis
from yt_downloader.routes import conversions, tasks
from yt_downloader.services.cleanup import cleanup_expired_files

logger = logging.getLogger(__name__)
_sleep = asyncio.sleep


async def cleanup_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(
                cleanup_expired_files,
                download_dir=settings.download_dir,
                ttl_hours=settings.file_ttl_hours,
            )
        except Exception:
            logger.exception("Cleanup task failed")
        await _sleep(settings.cleanup_interval_minutes * 60)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    if not hasattr(app.state, "redis"):
        app.state.redis = await get_redis()
    ensure_background_tasks(app)
    app.state.cleanup_task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        app.state.cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await app.state.cleanup_task
        await cancel_background_tasks(app)
        await close_redis()


def create_app() -> FastAPI:
    app = FastAPI(title="YT Downloader API", lifespan=lifespan)
    app.include_router(tasks.router, prefix="/api")
    app.include_router(conversions.router, prefix="/api")
    return app


app = create_app()
