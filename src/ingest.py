"""
Orchestrates all Spotify API calls, caches raw responses, and loads DuckDB.

Designed to be idempotent: re-running replaces existing rows without
creating duplicates (see db.upsert for the delete-then-insert strategy).
"""
from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import spotipy

from . import transform as T
from .api import call_with_retry
from .db import get_connection, upsert

logger = logging.getLogger(__name__)

RAW_DIR = Path("data/raw")
TIME_RANGES = ("short_term", "medium_term", "long_term")
AUDIO_FEATURE_BATCH_SIZE = 100  # Spotify's max per request


# ---------------------------------------------------------------------------
# Raw caching
# ---------------------------------------------------------------------------

def _save_raw(name: str, records: list[Any]) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RAW_DIR / f"{name}_{ts}.jsonl.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")
    logger.info("Cached %d records → %s", len(records), path.name)


# ---------------------------------------------------------------------------
# Fetch functions
# ---------------------------------------------------------------------------

def fetch_top_tracks(sp: spotipy.Spotify, time_range: str) -> list[dict]:
    logger.info("Fetching top tracks [%s]", time_range)
    resp = call_with_retry(sp.current_user_top_tracks, limit=50, time_range=time_range)
    items = resp["items"]
    _save_raw(f"top_tracks_{time_range}", items)
    return items


def fetch_top_artists(sp: spotipy.Spotify, time_range: str) -> list[dict]:
    logger.info("Fetching top artists [%s]", time_range)
    resp = call_with_retry(sp.current_user_top_artists, limit=50, time_range=time_range)
    items = resp["items"]
    _save_raw(f"top_artists_{time_range}", items)
    return items


def fetch_saved_tracks(sp: spotipy.Spotify) -> list[dict]:
    """Fetch all liked/saved tracks, paging through the full library."""
    logger.info("Fetching saved tracks (paginating)…")
    items: list[dict] = []
    resp = call_with_retry(sp.current_user_saved_tracks, limit=50, offset=0)
    while resp:
        items.extend(resp["items"])
        logger.debug("  %d saved tracks so far", len(items))
        resp = call_with_retry(sp.next, resp) if resp.get("next") else None
    _save_raw("saved_tracks", items)
    return items


def fetch_audio_features(sp: spotipy.Spotify, track_ids: list[str]) -> list[dict]:
    """Fetch audio features in batches of 100, gracefully skipping on 403.

    Spotify restricted audio_features for apps without extended quota access
    in late 2024. A 403 response returns an empty list so downstream code
    continues with NULL feature columns rather than crashing.
    """
    logger.info("Fetching audio features for %d unique tracks", len(track_ids))
    features: list[dict] = []
    for i in range(0, len(track_ids), AUDIO_FEATURE_BATCH_SIZE):
        batch = track_ids[i : i + AUDIO_FEATURE_BATCH_SIZE]
        try:
            result = call_with_retry(sp.audio_features, batch)
            features.extend(r for r in result if r is not None)
        except spotipy.SpotifyException as exc:
            if exc.http_status == 403:
                logger.warning(
                    "audio_features returned 403 — your app may need extended quota "
                    "access (see README). Audio feature columns will be NULL."
                )
                return []
            raise
    _save_raw("audio_features", features)
    return features


def fetch_artist_details(sp: spotipy.Spotify, artist_ids: list[str]) -> list[dict]:
    """Fetch full artist objects (with genres, popularity, followers) in batches of 50.

    The top-artists endpoint now returns simplified objects without genres, so
    this separate call is required to get genre data.
    """
    logger.info("Enriching %d artists with full details (genres, popularity)…", len(artist_ids))
    full_artists: list[dict] = []
    for i in range(0, len(artist_ids), 50):
        batch = artist_ids[i : i + 50]
        try:
            result = call_with_retry(sp.artists, batch)
            full_artists.extend(a for a in result["artists"] if a is not None)
        except spotipy.SpotifyException as exc:
            if exc.http_status == 403:
                logger.warning("artists endpoint returned 403 — genre data unavailable for this app.")
                return []
            raise
    _save_raw("artists_full", full_artists)
    return full_artists


def fetch_recently_played(sp: spotipy.Spotify) -> list[dict]:
    logger.info("Fetching recently played tracks")
    resp = call_with_retry(sp.current_user_recently_played, limit=50)
    items = resp["items"]
    _save_raw("recently_played", items)
    return items


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(sp: spotipy.Spotify) -> None:
    """Pull all data from Spotify and load it into DuckDB. Idempotent."""
    conn = get_connection()

    all_track_items: list[dict] = []
    all_artist_items: list[dict] = []

    for time_range in TIME_RANGES:
        track_items = fetch_top_tracks(sp, time_range)
        artist_items = fetch_top_artists(sp, time_range)

        upsert(conn, "top_tracks",  T.top_tracks_table(track_items, time_range),  ["track_id", "time_range"])
        upsert(conn, "top_artists", T.top_artists_table(artist_items, time_range), ["artist_id", "time_range"])

        all_track_items.extend(track_items)
        all_artist_items.extend(artist_items)

    saved_items = fetch_saved_tracks(sp)
    upsert(conn, "saved_tracks", T.saved_tracks_table(saved_items), ["track_id"])
    all_track_items.extend(saved_items)

    recent_items = fetch_recently_played(sp)
    upsert(conn, "recently_played", T.recently_played_table(recent_items), ["track_id", "played_at"])
    all_track_items.extend(recent_items)

    # Build a deduplicated tracks DataFrame and attach audio features.
    tracks_df = T.tracks_from_raw(all_track_items)
    features  = fetch_audio_features(sp, tracks_df["track_id"].tolist())
    tracks_df = T.merge_audio_features(tracks_df, features)
    upsert(conn, "tracks", tracks_df, ["track_id"])

    # Enrich top-artist objects with full details (genres, popularity, followers).
    # The top-artists endpoint returns simplified objects without these fields.
    unique_top_ids = list({a["id"] for a in all_artist_items})
    full_artist_items = fetch_artist_details(sp, unique_top_ids)

    artists_df = T.artists_from_raw(full_artist_items)
    track_artists_df = T.artists_from_tracks(all_track_items)
    new_ids = set(track_artists_df["artist_id"]) - set(artists_df["artist_id"])
    if new_ids:
        extra = track_artists_df[track_artists_df["artist_id"].isin(new_ids)]
        artists_df = pd.concat([artists_df, extra], ignore_index=True)
    upsert(conn, "artists", artists_df, ["artist_id"])

    conn.close()
    logger.info("Ingestion complete.")
