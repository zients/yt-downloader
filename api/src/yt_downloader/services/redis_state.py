import inspect
from collections.abc import Mapping
from typing import Any


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def write_hash_state(
    redis_client: Any,
    key: str,
    mapping: Mapping[str, Any],
    ttl_seconds: int,
) -> None:
    pipeline = redis_client.pipeline(transaction=True)
    try:
        await _maybe_await(pipeline.hset(key, mapping=dict(mapping)))
        await _maybe_await(pipeline.expire(key, ttl_seconds))
        await _maybe_await(pipeline.execute())
    finally:
        reset = getattr(pipeline, "reset", None)
        if reset is not None:
            await _maybe_await(reset())


async def _delete_key(redis_client: Any, key: str) -> None:
    delete = getattr(redis_client, "delete", None)
    if delete is not None:
        try:
            await _maybe_await(delete(key))
        except Exception:
            pass


async def write_failure_state(
    redis_client: Any,
    key: str,
    mapping: Mapping[str, Any],
    ttl_seconds: int,
) -> None:
    try:
        await write_hash_state(redis_client, key, mapping, ttl_seconds)
        return
    except Exception:
        pass

    try:
        await _maybe_await(redis_client.hset(key, mapping=dict(mapping)))
    except Exception:
        await _delete_key(redis_client, key)
        return

    ttl = getattr(redis_client, "ttl", None)
    if ttl is not None:
        try:
            if await _maybe_await(ttl(key)) > 0:
                return
        except Exception:
            pass

    try:
        await _maybe_await(redis_client.expire(key, ttl_seconds))
    except Exception:
        await _delete_key(redis_client, key)
