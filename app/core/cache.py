import json
import redis
from typing import Dict, Any
import logging

from app.core.config import REDIS_HOST, REDIS_PORT, CACHE_TTL_SECONDS
from app.schemas.db import load_data   # This pulls the full dataset from PostgreSQL

logger = logging.getLogger(__name__)

# Global Redis client (created once when the module is imported)
redis_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    decode_responses=True,      # Automatically converts bytes to str
    socket_timeout=5,
    socket_connect_timeout=5,
    retry_on_timeout=True
)

CACHE_KEY = "sociomed:full_data"   # All products, inventory, pricing, etc.

def get_cached_data() -> Dict[str, Any]:
    """
    Returns the full dataset (products, vendors, inventory, pricing, aliases)
    from Redis cache if available, otherwise loads from PostgreSQL and caches it.
    """
    # 1. Try Redis first (super fast)
    try:
        cached = redis_client.get(CACHE_KEY)
        if cached:
            logger.debug("✅ Data loaded from Redis cache")
            return json.loads(cached)
    except Exception as e:
        logger.warning(f"Redis cache read failed: {e}. Falling back to DB.")

    # 2. Fallback: Load fresh data from PostgreSQL
    logger.info("📥 Loading data from PostgreSQL (cache miss)")
    data = load_data()

    # 3. Cache the result for future requests
    try:
        redis_client.setex(
            CACHE_KEY,
            CACHE_TTL_SECONDS,          # e.g. 300 seconds = 5 minutes
            json.dumps(data)
        )
        logger.info("✅ Data cached in Redis")
    except Exception as e:
        logger.warning(f"Failed to cache data in Redis: {e}")

    return data


# Optional helper if you ever need to clear the cache manually
def clear_cache() -> bool:
    """Clear the full dataset cache (useful after sync_sheets_to_db.py runs)."""
    try:
        redis_client.delete(CACHE_KEY)
        logger.info("🗑️ Full data cache cleared")
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False
