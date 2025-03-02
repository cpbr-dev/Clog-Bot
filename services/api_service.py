import aiohttp
import logging
import traceback
import time
import asyncio
from config import OSRS_API_URL

logger = logging.getLogger()

# Rate limiting settings
MAX_REQUESTS_PER_MINUTE = 14  # Set slightly below the limit (15) for safety
MAX_BURST = 90  # Below the 100 limit to be safe
_rate_limit_data = {
    "tokens": MAX_BURST,  # Start with max tokens
    "last_refill": time.time(),
    "queue": asyncio.Queue(),
    "processing": False,
}

async def rate_limit_processor():
    """Background task to process queued API requests with rate limiting"""
    _rate_limit_data["processing"] = True

    try:
        while True:
            # Get the next request from the queue
            callback, args, future = await _rate_limit_data["queue"].get()

            # Wait until we have a token available
            await ensure_token_available()

            # Execute the API call
            try:
                result = await callback(*args)
                future.set_result(result)
            except Exception as e:
                future.set_exception(e)
            finally:
                _rate_limit_data["queue"].task_done()
    except asyncio.CancelledError:
        logger.info("Rate limit processor task was cancelled")
        _rate_limit_data["processing"] = False
    except Exception as e:
        logger.error(f"Error in rate limit processor: {e}")
        logger.error(traceback.format_exc())
        _rate_limit_data["processing"] = False
        # Restart the task
        asyncio.create_task(rate_limit_processor())


def refill_tokens():
    """Refill rate limit tokens based on elapsed time"""
    current_time = time.time()
    elapsed = current_time - _rate_limit_data["last_refill"]

    # Calculate how many tokens to add (tokens accrue at MAX_REQUESTS_PER_MINUTE per 60 seconds)
    new_tokens = int(elapsed * (MAX_REQUESTS_PER_MINUTE / 60.0))

    if new_tokens > 0:
        _rate_limit_data["tokens"] = min(
            MAX_BURST, _rate_limit_data["tokens"] + new_tokens
        )
        _rate_limit_data["last_refill"] = current_time
        logger.debug(
            f"Refilled {new_tokens} API tokens, now at {_rate_limit_data['tokens']}/{MAX_BURST}"
        )


async def ensure_token_available():
    """Wait until at least one token is available"""
    while True:
        refill_tokens()
        if _rate_limit_data["tokens"] > 0:
            _rate_limit_data["tokens"] -= 1
            logger.debug(f"Using API token, {_rate_limit_data['tokens']} remaining")
            return
        # Wait a bit before checking again
        wait_time = 60.0 / MAX_REQUESTS_PER_MINUTE
        logger.warning(f"Out of API rate limit tokens, waiting {wait_time:.2f} seconds")
        await asyncio.sleep(wait_time)


async def enqueue_api_request(callback, *args):
    """Add an API request to the rate-limited queue"""
    # Create a future that will be resolved when the request completes
    future = asyncio.Future()

    # Add the request to the queue
    await _rate_limit_data["queue"].put((callback, args, future))

    # Start the processor if it's not already running
    if not _rate_limit_data["processing"]:
        asyncio.create_task(rate_limit_processor())

    # Wait for the request to complete
    return await future


async def _fetch_collection_log_internal(username):
    """Internal function to fetch collection log data without rate limiting"""
    logger.debug(f"Fetching collection log for {username} from API")
    url = f"{OSRS_API_URL}{username}"

    async with aiohttp.ClientSession() as session:
        try:
            logger.info(f"Making API request to {url} for user {username}")
            start_time = time.time()
            async with session.get(url) as response:
                elapsed = time.time() - start_time
                logger.info(
                    f"API response received in {elapsed:.2f}s with status code {response.status}"
                )

                if response.status == 200:
                    try:
                        data = await response.json()
                        logger.debug(
                            f"Successfully parsed JSON response for {username}"
                        )
                        for activity in data.get("activities", []):
                            if activity["id"] == 18:  # Collections Logged
                                result = {
                                    "score": activity["score"],
                                    "rank": activity["rank"],
                                }
                                logger.info(
                                    f"Found collection log data for {username}: score={activity['score']}, rank={activity['rank']}"
                                )
                                return result
                        # No collection log data found
                        logger.info(f"No collection log data found for {username}")
                        return {"score": -1, "rank": -1}
                    except Exception as e:
                        logger.error(f"Error parsing API response: {e}")
                        logger.error(traceback.format_exc())
                elif response.status == 429:  # Rate limited
                    retry_after = response.headers.get("Retry-After", "60")
                    try:
                        retry_seconds = int(retry_after)
                    except ValueError:
                        retry_seconds = 60

                    logger.warning(
                        f"Rate limited by OSRS API! Need to wait {retry_seconds} seconds"
                    )
                    # Adjust our token pool to reflect rate limiting
                    _rate_limit_data["tokens"] = 0
                    # Wait the suggested time plus a small buffer
                    await asyncio.sleep(retry_seconds + 1)
                    logger.info("Retrying after rate limit delay")
                    return None  # Return None to indicate retry needed
                else:
                    logger.warning(
                        f"Unexpected status code {response.status} for {username}"
                    )
                    if response.status >= 500:
                        # Server error, might be temporary
                        logger.info(
                            f"OSRS server error {response.status}, will retry later"
                        )
                        return None
        except aiohttp.ClientError as e:
            logger.error(f"HTTP client error for {username}: {e}")
            logger.error(traceback.format_exc())
        except Exception as e:
            logger.error(f"Exception in API call: {e}")
            logger.error(traceback.format_exc())

    logger.error(f"Failed to fetch collection log for {username}")
    return None


async def fetch_collection_log(username, max_retries=2):
    """Fetch collection log data with rate limiting"""
    # Rate-limited API call with retries
    for attempt in range(max_retries + 1):
        if attempt > 0:
            logger.info(f"Retry attempt {attempt}/{max_retries} for {username}")

        # Enqueue the API request with rate limiting
        result = await enqueue_api_request(
            _fetch_collection_log_internal, username
        )

        if result is not None:
            return result

        # If we get None, it indicates we should retry after a delay
        if attempt < max_retries:
            # Exponential backoff
            delay = 2**attempt
            logger.info(f"Backing off for {delay} seconds before retrying {username}")
            await asyncio.sleep(delay)

    # All retries failed
    logger.error(f"All {max_retries + 1} attempts failed for {username}")
    return None
