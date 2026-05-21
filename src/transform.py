"""
Pure functions that convert raw Spotify API dicts into clean pandas DataFrames.

Each function is stateless and has no side effects, making them straightforward
to unit-test with small fixture data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pandas as pd

_AUDIO_FEATURE_COLS = [
    "danceability", "energy", "key", "loudness", "mode",
    "speechiness", "acousticness", "instrumentalness",
    "liveness", "valence", "tempo", "time_signature",
]


# ---------------------------------------------------------------------------
# Tracks
# ---------------------------------------------------------------------------

def tracks_from_raw(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Extract a track-level DataFrame from a list of Spotify track objects.

    Accepts items from top-tracks (bare track objects), saved-tracks, or
    recently-played responses (both wrapped as {"track": {...}, ...}).
    Deduplicates by track_id. Audio feature columns are initialised to None
    and filled later by merge_audio_features().
    """
    rows = []
    for item in items:
        track = item.get("track", item)  # unwrap saved/recently-played envelope
        rows.append({
            "track_id":     track["id"],
            "name":         track["name"],
            "artist_ids":   [a["id"]   for a in track.get("artists", [])],
            "artist_names": [a["name"] for a in track.get("artists", [])],
            "album_name":   track.get("album", {}).get("name"),
            "release_date": track.get("album", {}).get("release_date"),
            "duration_ms":  track.get("duration_ms"),
            "popularity":   track.get("popularity"),
            "explicit":     track.get("explicit", False),
            **{col: None for col in _AUDIO_FEATURE_COLS},
            "is_demo":      False,
        })
    return pd.DataFrame(rows).drop_duplicates("track_id").reset_index(drop=True)


def merge_audio_features(
    tracks_df: pd.DataFrame,
    features: list[dict[str, Any]],
) -> pd.DataFrame:
    """Left-join audio features onto a tracks DataFrame keyed on track_id.

    If features is empty or all-None (e.g. API returned 403), returns
    tracks_df unchanged with audio feature columns remaining as None.
    """
    valid = [f for f in features if f is not None]
    if not valid:
        return tracks_df

    feat_df = pd.DataFrame([
        {"track_id": f["id"], **{col: f.get(col) for col in _AUDIO_FEATURE_COLS}}
        for f in valid
    ])

    # Drop the None-initialised placeholder columns before merging real values.
    non_feature_cols = [c for c in tracks_df.columns if c not in _AUDIO_FEATURE_COLS]
    return tracks_df[non_feature_cols].merge(feat_df, on="track_id", how="left")


# ---------------------------------------------------------------------------
# Artists
# ---------------------------------------------------------------------------

def artists_from_raw(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Extract an artist DataFrame from top-artists API response items."""
    rows = []
    for artist in items:
        rows.append({
            "artist_id":  artist["id"],
            "name":       artist["name"],
            "genres":     artist.get("genres", []),
            "popularity": artist.get("popularity"),
            "followers":  artist.get("followers", {}).get("total"),
        })
    return pd.DataFrame(rows).drop_duplicates("artist_id").reset_index(drop=True)


def artists_from_tracks(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Extract minimal artist rows (id + name only) from track items.

    Used to ensure every artist referenced by a track exists in the artists
    table even if they never appeared in the top-artists endpoint.
    """
    rows = []
    for item in items:
        track = item.get("track", item)
        for artist in track.get("artists", []):
            rows.append({
                "artist_id":  artist["id"],
                "name":       artist["name"],
                "genres":     [],
                "popularity": None,
                "followers":  None,
            })
    return pd.DataFrame(rows).drop_duplicates("artist_id").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Junction / event tables
# ---------------------------------------------------------------------------

def top_tracks_table(items: list[dict[str, Any]], time_range: str) -> pd.DataFrame:
    """Build the top_tracks ranking table from a top-tracks API response."""
    captured_at = datetime.now(timezone.utc)
    return pd.DataFrame([
        {
            "track_id":   item["id"],
            "time_range": time_range,
            "rank":       rank,
            "captured_at": captured_at,
        }
        for rank, item in enumerate(items, start=1)
    ])


def top_artists_table(items: list[dict[str, Any]], time_range: str) -> pd.DataFrame:
    """Build the top_artists ranking table from a top-artists API response."""
    captured_at = datetime.now(timezone.utc)
    return pd.DataFrame([
        {
            "artist_id":  item["id"],
            "time_range": time_range,
            "rank":       rank,
            "captured_at": captured_at,
        }
        for rank, item in enumerate(items, start=1)
    ])


def recently_played_table(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the recently_played table from a recently-played API response."""
    rows = [
        {
            "track_id": item["track"]["id"],
            "played_at": pd.to_datetime(item["played_at"]),
        }
        for item in items
    ]
    return pd.DataFrame(rows).drop_duplicates(["track_id", "played_at"]).reset_index(drop=True)


def saved_tracks_table(items: list[dict[str, Any]]) -> pd.DataFrame:
    """Build the saved_tracks table from a saved-tracks API response."""
    rows = [
        {
            "track_id": item["track"]["id"],
            "added_at": pd.to_datetime(item["added_at"]),
        }
        for item in items
    ]
    return pd.DataFrame(rows).drop_duplicates("track_id").reset_index(drop=True)
