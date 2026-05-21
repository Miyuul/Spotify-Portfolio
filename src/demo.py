"""
Populates synthetic audio features for tracks that have NULL features.

Run this after ingestion when the Spotify audio-features API is unavailable (403).
Features are generated using Beta/Normal distributions fitted to published
statistics of the Spotify audio-features dataset.

Usage:
    uv run python -m src.demo
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .db import get_connection

# Reproducible synthetic data — change the seed if you want a different draw.
_RNG = np.random.default_rng(seed=42)


def _generate_features(n: int) -> pd.DataFrame:
    """Return n rows of synthetic audio features with realistic distributions."""
    return pd.DataFrame({
        # Beta(a, b) keeps values in [0, 1]; parameters chosen to match known
        # Spotify dataset means and skew directions from published analyses.
        "danceability":     _RNG.beta(2.5, 2.0, n),   # mean ≈ 0.56, mild right skew
        "energy":           _RNG.beta(2.8, 2.0, n),   # mean ≈ 0.58, slight right skew
        "valence":          _RNG.beta(2.0, 2.2, n),   # mean ≈ 0.48, near-symmetric
        "acousticness":     _RNG.beta(1.0, 2.5, n),   # mean ≈ 0.29, right skew
        "speechiness":      _RNG.beta(1.0, 8.0, n),   # mean ≈ 0.11, very right skew
        "instrumentalness": _RNG.beta(0.5, 4.0, n),   # mean ≈ 0.11, most near 0
        "liveness":         _RNG.beta(1.5, 6.0, n),   # mean ≈ 0.20, right skew
        "key":              _RNG.integers(0, 12, n).astype(float),
        "loudness":         _RNG.normal(-8.0, 4.0, n).clip(-30.0, 0.0),
        "mode":             _RNG.binomial(1, 0.6, n).astype(float),  # 60 % major
        "tempo":            _RNG.normal(120.0, 28.0, n).clip(60.0, 200.0),
        # Strongly weighted toward 4/4 time
        "time_signature":   _RNG.choice([3, 4, 4, 4, 4, 5], n).astype(float),
    })


def run() -> None:
    conn = get_connection()  # also runs the is_demo migration if needed

    missing = conn.execute(
        "SELECT track_id FROM tracks WHERE danceability IS NULL"
    ).df()

    if missing.empty:
        print("All tracks already have audio features — nothing to do.")
        conn.close()
        return

    n = len(missing)
    print(f"Generating synthetic audio features for {n} tracks…")

    features = _generate_features(n)
    features.insert(0, "track_id", missing["track_id"].values)

    conn.register("_demo", features)
    conn.execute("""
        UPDATE tracks
        SET danceability     = _demo.danceability,
            energy           = _demo.energy,
            valence          = _demo.valence,
            acousticness     = _demo.acousticness,
            speechiness      = _demo.speechiness,
            instrumentalness = _demo.instrumentalness,
            liveness         = _demo.liveness,
            key              = CAST(_demo.key AS INTEGER),
            loudness         = _demo.loudness,
            mode             = CAST(_demo.mode AS INTEGER),
            tempo            = _demo.tempo,
            time_signature   = CAST(_demo.time_signature AS INTEGER),
            is_demo          = TRUE
        FROM _demo
        WHERE tracks.track_id = _demo.track_id
    """)
    conn.unregister("_demo")
    conn.close()
    print(f"Done. {n} tracks updated with synthetic features (is_demo = TRUE).")


if __name__ == "__main__":
    run()
