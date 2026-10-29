from pymongo import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

from .config import get_settings

_client: AsyncMongoClient | None = None


def get_db() -> AsyncDatabase:
    global _client
    s = get_settings()
    if _client is None:
        _client = AsyncMongoClient(s.mongodb_uri, tz_aware=True)
    return _client[s.mongodb_db]


async def close_db() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
