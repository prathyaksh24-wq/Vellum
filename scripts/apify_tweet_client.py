"""Thin wrapper around the Apify apidojo/tweet-scraper actor."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from apify_client import ApifyClient

ACTOR_ID = "apidojo~tweet-scraper"
DEFAULT_TIMEOUT_SECS = 120


def fetch_tweets(
    *,
    handle: str,
    start: datetime,
    end: datetime,
    max_items: int,
    token: str,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
) -> list[dict[str, Any]]:
    """Run the tweet-scraper actor for `handle` between `start` and `end`.

    Returns the raw dataset items. Raises RuntimeError on actor failure.
    """
    client = ApifyClient(token)
    run_input = {
        "twitterHandles": [handle],
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "maxItems": max_items,
        "sort": "Latest",
        "tweetLanguage": "en",
    }
    run = client.actor(ACTOR_ID).call(run_input=run_input, timeout_secs=timeout_secs)
    if not run or not run.get("defaultDatasetId"):
        raise RuntimeError("Apify actor returned no dataset")
    dataset_id = run["defaultDatasetId"]
    return list(client.dataset(dataset_id).iterate_items())
