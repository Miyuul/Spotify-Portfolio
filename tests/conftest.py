# Minimal fixtures that mirror the shape of real Spotify API responses.
# Only the fields actually used by transform.py are included.

SAMPLE_TRACK = {
    "id": "track001",
    "name": "Test Track",
    "artists": [{"id": "artist001", "name": "Test Artist"}],
    "album": {"name": "Test Album", "release_date": "2023-01-01"},
    "duration_ms": 200_000,
    "popularity": 75,
    "explicit": False,
}

SAMPLE_TRACK_2 = {
    "id": "track002",
    "name": "Another Track",
    "artists": [
        {"id": "artist001", "name": "Test Artist"},
        {"id": "artist002", "name": "Other Artist"},
    ],
    "album": {"name": "Another Album", "release_date": "2022-06-15"},
    "duration_ms": 180_000,
    "popularity": 60,
    "explicit": True,
}

SAMPLE_ARTIST = {
    "id": "artist001",
    "name": "Test Artist",
    "genres": ["indie pop", "dream pop"],
    "popularity": 80,
    "followers": {"total": 500_000},
}

SAMPLE_AUDIO_FEATURE = {
    "id": "track001",
    "danceability": 0.7,
    "energy": 0.8,
    "key": 5,
    "loudness": -5.0,
    "mode": 1,
    "speechiness": 0.05,
    "acousticness": 0.1,
    "instrumentalness": 0.0,
    "liveness": 0.12,
    "valence": 0.65,
    "tempo": 120.0,
    "time_signature": 4,
}

SAMPLE_RECENTLY_PLAYED_ITEM = {
    "track": SAMPLE_TRACK,
    "played_at": "2024-01-15T10:30:00.000Z",
}

SAMPLE_SAVED_TRACK_ITEM = {
    "track": SAMPLE_TRACK_2,
    "added_at": "2024-01-10T08:00:00Z",
}
