import pytest

from yt_downloader.services.redis_state import write_failure_state


@pytest.mark.asyncio
async def test_write_failure_state_rejects_non_positive_ttl(fake_redis) -> None:
    persisted = await write_failure_state(
        fake_redis,
        "task:zero-ttl",
        {"status": "failed", "error": "boom"},
        ttl_seconds=0,
    )

    assert persisted is False
    assert await fake_redis.hgetall("task:zero-ttl") == {}
