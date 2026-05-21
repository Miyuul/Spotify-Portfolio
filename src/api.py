import logging
import time
from typing import Any, Callable

import spotipy

logger = logging.getLogger(__name__)

_MAX_RETRIES = 5
_BASE_BACKOFF = 2.0  # seconds; doubles each retry


def call_with_retry(fn: Callable, *args: Any, **kwargs: Any) -> Any:
    """Call a Spotipy API function and retry on 429 rate-limit responses.

    Spotipy doesn't expose the Retry-After header on SpotifyException, so we
    use exponential backoff starting at _BASE_BACKOFF seconds.
    """
    for attempt in range(_MAX_RETRIES):
        try:
            return fn(*args, **kwargs)
        except spotipy.SpotifyException as exc:
            if exc.http_status == 429:
                sleep_for = _BASE_BACKOFF * (2 ** attempt)
                logger.warning(
                    "Rate limited (429). Sleeping %.0fs (attempt %d/%d).",
                    sleep_for, attempt + 1, _MAX_RETRIES,
                )
                time.sleep(sleep_for)
            else:
                raise
    raise RuntimeError(
        f"Exceeded {_MAX_RETRIES} retries calling {getattr(fn, '__name__', repr(fn))}"
    )
