"""Create (or update) a MongoDB TTL index without ever stopping the application."""
import logging

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.errors import OperationFailure

logger = logging.getLogger(__name__)

# Mongo error codes raised when an index with this name exists with different options / keys.
INDEX_CONFLICT_CODES = (85, 86)


async def ensure_ttl_index(db: AsyncDatabase, collection: AsyncCollection, field: str, name: str, seconds: int) -> None:
    """MongoDB itself deletes documents whose `field` is older than `seconds`.

    Some Mongo-compatible servers do not implement TTL indexes, so a failure is logged and swallowed:
    the other indexes stay in place and the app keeps running (old data just will not expire).
    """
    try:
        await collection.create_index(field, expireAfterSeconds=seconds, name=name)
    except OperationFailure as exc:
        if exc.code in INDEX_CONFLICT_CODES:
            try:  # the retention setting changed: update the existing TTL index in place
                await db.command({"collMod": collection.name, "index": {"name": name, "expireAfterSeconds": seconds}})
                return
            except OperationFailure as inner:
                exc = inner
        logger.warning("Could not create TTL index %s on %s (%s); old documents will not expire automatically", name, collection.name, exc)
