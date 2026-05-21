from pathlib import Path

import duckdb
import pandas as pd

_DB_PATH = Path("data/spotify.duckdb")

_DDL = """
CREATE TABLE IF NOT EXISTS tracks (
    track_id            VARCHAR PRIMARY KEY,
    name                VARCHAR NOT NULL,
    artist_ids          VARCHAR[],
    artist_names        VARCHAR[],
    album_name          VARCHAR,
    release_date        VARCHAR,
    duration_ms         INTEGER,
    popularity          INTEGER,
    explicit            BOOLEAN,
    danceability        FLOAT,
    energy              FLOAT,
    key                 INTEGER,
    loudness            FLOAT,
    mode                INTEGER,
    speechiness         FLOAT,
    acousticness        FLOAT,
    instrumentalness    FLOAT,
    liveness            FLOAT,
    valence             FLOAT,
    tempo               FLOAT,
    time_signature      INTEGER,
    is_demo             BOOLEAN DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS artists (
    artist_id   VARCHAR PRIMARY KEY,
    name        VARCHAR NOT NULL,
    genres      VARCHAR[],
    popularity  INTEGER,
    followers   INTEGER
);

CREATE TABLE IF NOT EXISTS top_tracks (
    track_id    VARCHAR NOT NULL,
    time_range  VARCHAR NOT NULL,
    rank        INTEGER NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    PRIMARY KEY (track_id, time_range)
);

CREATE TABLE IF NOT EXISTS top_artists (
    artist_id   VARCHAR NOT NULL,
    time_range  VARCHAR NOT NULL,
    rank        INTEGER NOT NULL,
    captured_at TIMESTAMP NOT NULL,
    PRIMARY KEY (artist_id, time_range)
);

CREATE TABLE IF NOT EXISTS recently_played (
    track_id    VARCHAR NOT NULL,
    played_at   TIMESTAMP NOT NULL,
    PRIMARY KEY (track_id, played_at)
);

CREATE TABLE IF NOT EXISTS saved_tracks (
    track_id    VARCHAR PRIMARY KEY,
    added_at    TIMESTAMP NOT NULL
);
"""


def get_connection() -> duckdb.DuckDBPyConnection:
    """Open (or create) the local DuckDB file and ensure all tables exist."""
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = duckdb.connect(str(_DB_PATH))
    conn.execute(_DDL)
    # Migration: add is_demo to databases created before this column existed.
    conn.execute("ALTER TABLE tracks ADD COLUMN IF NOT EXISTS is_demo BOOLEAN DEFAULT FALSE")
    return conn


def upsert(
    conn: duckdb.DuckDBPyConnection,
    table: str,
    df: pd.DataFrame,
    keys: list[str],
) -> None:
    """Delete rows whose keys overlap with df, then insert df.

    This delete-then-insert pattern is the idempotent upsert strategy for
    DuckDB, which doesn't support ON CONFLICT DO UPDATE for composite keys
    via the pandas integration path.
    """
    if df.empty:
        return
    conn.register("_staging", df)
    if len(keys) == 1:
        conn.execute(
            f"DELETE FROM {table} WHERE {keys[0]} IN (SELECT {keys[0]} FROM _staging)"
        )
    else:
        key_tuple = ", ".join(keys)
        conn.execute(
            f"DELETE FROM {table} WHERE ({key_tuple}) IN "
            f"(SELECT {key_tuple} FROM _staging)"
        )
    # Insert by name so column order in the DataFrame never has to match the DDL.
    cols = ", ".join(f'"{c}"' for c in df.columns)
    conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM _staging")
    conn.unregister("_staging")
