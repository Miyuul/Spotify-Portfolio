"""
Enriches the artists table with genre tags fetched from the Last.fm API.
Run this once after ingestion to populate the genres chart in the dashboard.

Usage:
    uv run python -m src.enrich
"""
from __future__ import annotations

import logging
import os
import time

import requests
from dotenv import load_dotenv

from .db import get_connection

load_dotenv()

LASTFM_URL = "http://ws.audioscrobbler.com/2.0/"
MAX_TAGS   = 5    # top N genre tags to store per artist
DELAY      = 0.2  # seconds between requests — stays well under Last.fm's rate limit

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)-8s — %(message)s",
)


def _fetch_tags(artist_name: str, api_key: str) -> list[str]:
    """Return up to MAX_TAGS genre tags for an artist from Last.fm."""
    try:
        resp = requests.get(
            LASTFM_URL,
            params={
                "method":  "artist.getinfo",
                "artist":  artist_name,
                "api_key": api_key,
                "format":  "json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            return []
        tags = data.get("artist", {}).get("tags", {}).get("tag", [])
        return [t["name"].lower() for t in tags[:MAX_TAGS]]
    except Exception:
        return []


def run() -> None:
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        print("ERROR: LASTFM_API_KEY not set in .env")
        return

    conn = get_connection()
    artists = conn.execute("SELECT artist_id, name FROM artists").df()
    total = len(artists)
    print(f"Fetching genres for {total} artists from Last.fm…")

    genres_map: dict[str, list[str]] = {}
    for i, row in artists.iterrows():
        genres_map[row["artist_id"]] = _fetch_tags(row["name"], api_key)
        if (i + 1) % 100 == 0:
            found = sum(1 for g in genres_map.values() if g)
            print(f"  {i + 1}/{total} processed  ({found} with genre tags so far)")
        time.sleep(DELAY)

    artists["genres"] = artists["artist_id"].map(genres_map)

    conn.register("_genres", artists[["artist_id", "genres"]])
    conn.execute("""
        UPDATE artists
        SET genres = _genres.genres
        FROM _genres
        WHERE artists.artist_id = _genres.artist_id
    """)
    conn.unregister("_genres")
    conn.close()

    with_genres = sum(1 for g in genres_map.values() if g)
    print(f"Done. {with_genres}/{total} artists now have genre tags.")


if __name__ == "__main__":
    run()
