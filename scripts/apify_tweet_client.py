"""Thin wrapper around the Apify patient_discovery/twitter-user-tweets actor.

This actor returns the most recent ~20 tweets for a given username on free tier.
It does NOT support date-range pagination, so `start`/`end` are accepted on the
function signature for compatibility with the polling/backfill drivers, but the
actor only ever returns recent items. Backfill scenarios will see no growth.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from apify_client import ApifyClient

ACTOR_ID = "patient_discovery/twitter-user-tweets"
DEFAULT_TIMEOUT_SECS = 120
MIN_RUN_ITEMS_FLOOR = 20  # the actor's minimum cost cap requires >=20


def fetch_tweets(
    *,
    handle: str,
    start: datetime,
    end: datetime,
    max_items: int,
    token: str,
    timeout_secs: int = DEFAULT_TIMEOUT_SECS,
) -> list[dict[str, Any]]:
    """Run the twitter-user-tweets actor for `handle`.

    `start` and `end` are ignored by this actor; preserved on the signature for
    drop-in compatibility with the existing polling/backfill drivers.
    `max_items` is honoured both as the actor input hint and the SDK-level cost
    cap, floored to MIN_RUN_ITEMS_FLOOR to avoid 'maximum cost $0.00' aborts.

    Returns the raw dataset items. Raises RuntimeError on actor failure.
    """
    client = ApifyClient(token)
    effective_max = max(max_items, MIN_RUN_ITEMS_FLOOR)
    run_input = {
        "usernames": [handle],
        "tweetsDesired": effective_max,
    }
    run = client.actor(ACTOR_ID).call(
        run_input=run_input,
        timeout_secs=timeout_secs,
        max_items=effective_max,
    )
    if not run or not run.get("defaultDatasetId"):
        raise RuntimeError("Apify actor returned no dataset")
    dataset_id = run["defaultDatasetId"]
    return list(client.dataset(dataset_id).iterate_items())
