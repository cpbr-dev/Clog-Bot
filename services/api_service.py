import aiohttp
import logging
import traceback
import time
import asyncio
from config import OSRS_API_URL

logger = logging.getLogger()

# Add caching to reduce API calls
_cache = {}  # username -> (timestamp, data)
CACHE_TTL = 3600  # 1 hour cache


async def fetch_collection_log(username, bypass_cache=False):
    """Fetch collection log data with caching to reduce API calls"""
    current_time = time.time()

    # Return cached result if available and not expired
    cache_key = username.lower()
    if not bypass_cache and cache_key in _cache:
        timestamp, data = _cache[cache_key]
        if current_time - timestamp < CACHE_TTL:
            logger.debug(f"Using cached data for {username}")
            return data

    # Otherwise fetch from API
    logger.debug(f"Fetching collection log for {username} from API")
    url = f"{OSRS_API_URL}{username}"

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url) as response:
                if response.status == 200:
                    try:
                        data = await response.json()
                        for activity in data.get("activities", []):
                            if activity["id"] == 18:  # Collections Logged
                                result = {
                                    "score": activity["score"],
                                    "rank": activity["rank"],
                                }
                                _cache[cache_key] = (current_time, result)
                                return result
                        # No collection log data found
                        result = {"score": -1, "rank": -1}
                        _cache[cache_key] = (current_time, result)
                        return result
                    except Exception as e:
                        logger.error(f"Error parsing API response: {e}")
                        logger.error(traceback.format_exc())
                elif response.status == 429:  # Rate limited
                    logger.warning("Rate limited by OSRS API! Adding delay...")
                    await asyncio.sleep(3)  # Add delay before retrying
                    return await fetch_collection_log(username, bypass_cache)
        except Exception as e:
            logger.error(f"Exception in API call: {e}")

    return None
