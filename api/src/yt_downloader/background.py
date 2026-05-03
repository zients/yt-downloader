import asyncio
import logging
from collections.abc import Awaitable
from typing import Any

logger = logging.getLogger(__name__)


def ensure_background_tasks(app: Any) -> set[asyncio.Task[Any]]:
    if not hasattr(app.state, "background_tasks"):
        app.state.background_tasks = set()
    return app.state.background_tasks


def schedule_background_task(app: Any, awaitable: Awaitable[Any]) -> asyncio.Task[Any]:
    tasks = ensure_background_tasks(app)
    task = asyncio.create_task(awaitable)
    tasks.add(task)

    def consume_result(done_task: asyncio.Task[Any]) -> None:
        tasks.discard(done_task)
        try:
            done_task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Background task failed")

    task.add_done_callback(consume_result)
    return task


async def cancel_background_tasks(app: Any) -> None:
    tasks = set(ensure_background_tasks(app))
    if not tasks:
        return

    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    ensure_background_tasks(app).difference_update(tasks)
