import pytest

from yt_downloader import redis_client
from yt_downloader.config import settings


class FakeRedisClient:
    def __init__(self) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_get_redis_creates_reuses_and_closes_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_client = FakeRedisClient()
    calls = []

    def from_url(url: str, *, decode_responses: bool) -> FakeRedisClient:
        calls.append((url, decode_responses))
        return fake_client

    monkeypatch.setattr(redis_client, "_client", None)
    monkeypatch.setattr(redis_client.redis.Redis, "from_url", from_url)

    first = await redis_client.get_redis()
    second = await redis_client.get_redis()
    await redis_client.close_redis()

    assert first is fake_client
    assert second is fake_client
    assert calls == [(settings.redis_url, True)]
    assert fake_client.closed
    assert redis_client._client is None
