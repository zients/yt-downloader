import inspect
from collections.abc import Mapping
from typing import Any


class StatePersistenceError(RuntimeError):
    pass


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
    if ttl_seconds <= 0:
        raise StatePersistenceError("ttl_seconds must be positive")

    pipeline = redis_client.pipeline(transaction=True)
    try:
        try:
            await _maybe_await(pipeline.hset(key, mapping=dict(mapping)))
            await _maybe_await(pipeline.expire(key, ttl_seconds))
            results = await _maybe_await(pipeline.execute())
            if not results or not results[-1]:
                await _delete_key(redis_client, key)
                raise StatePersistenceError("failed to set state TTL")
        except StatePersistenceError:
            raise
        except Exception as exc:
            await _delete_key(redis_client, key)
            raise StatePersistenceError("failed to persist state") from exc
    finally:
        reset = getattr(pipeline, "reset", None)
        if reset is not None:
            await _maybe_await(reset())


async def _delete_key(redis_client: Any, key: str) -> bool:
    delete = getattr(redis_client, "delete", None)
    if delete is not None:
        try:
            deleted = await _maybe_await(delete(key))
            return bool(deleted)
        except Exception:
            pass
    return False


async def write_failure_state(
    redis_client: Any,
    key: str,
    mapping: Mapping[str, Any],
    ttl_seconds: int,
) -> bool:
    if ttl_seconds <= 0:
        await _delete_key(redis_client, key)
        return False

    try:
        await write_hash_state(redis_client, key, mapping, ttl_seconds)
        return True
    except Exception:
        pass

    try:
        await _maybe_await(redis_client.hset(key, mapping=dict(mapping)))
    except Exception:
        await _delete_key(redis_client, key)
        return False

    ttl = getattr(redis_client, "ttl", None)
    if ttl is not None:
        try:
            if await _maybe_await(ttl(key)) > 0:
                return True
        except Exception:
            pass

    try:
        if await _maybe_await(redis_client.expire(key, ttl_seconds)):
            return True
        await _delete_key(redis_client, key)
        return False
    except Exception:
        await _delete_key(redis_client, key)
        return False
