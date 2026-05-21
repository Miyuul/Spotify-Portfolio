import pandas as pd
import pytest

from src.transform import (
    artists_from_raw,
    artists_from_tracks,
    merge_audio_features,
    recently_played_table,
    saved_tracks_table,
    top_artists_table,
    top_tracks_table,
    tracks_from_raw,
)
from tests.conftest import (
    SAMPLE_ARTIST,
    SAMPLE_AUDIO_FEATURE,
    SAMPLE_RECENTLY_PLAYED_ITEM,
    SAMPLE_SAVED_TRACK_ITEM,
    SAMPLE_TRACK,
    SAMPLE_TRACK_2,
)


class TestTracksFromRaw:
    def test_bare_track_object(self):
        df = tracks_from_raw([SAMPLE_TRACK])
        assert len(df) == 1
        assert df.iloc[0]["track_id"] == "track001"
        assert df.iloc[0]["name"] == "Test Track"

    def test_artist_id_list(self):
        df = tracks_from_raw([SAMPLE_TRACK])
        assert df.iloc[0]["artist_ids"] == ["artist001"]

    def test_multiple_artists(self):
        df = tracks_from_raw([SAMPLE_TRACK_2])
        assert df.iloc[0]["artist_ids"] == ["artist001", "artist002"]
        assert len(df.iloc[0]["artist_names"]) == 2

    def test_unwraps_saved_track_envelope(self):
        df = tracks_from_raw([SAMPLE_SAVED_TRACK_ITEM])
        assert df.iloc[0]["track_id"] == "track002"

    def test_unwraps_recently_played_envelope(self):
        df = tracks_from_raw([SAMPLE_RECENTLY_PLAYED_ITEM])
        assert df.iloc[0]["track_id"] == "track001"

    def test_deduplicates_by_track_id(self):
        df = tracks_from_raw([SAMPLE_TRACK, SAMPLE_TRACK])
        assert len(df) == 1

    def test_audio_feature_cols_initialised_to_none(self):
        df = tracks_from_raw([SAMPLE_TRACK])
        assert pd.isna(df.iloc[0]["danceability"])
        assert pd.isna(df.iloc[0]["valence"])


class TestMergeAudioFeatures:
    def test_features_joined_on_matching_id(self):
        tracks_df = tracks_from_raw([SAMPLE_TRACK])
        result = merge_audio_features(tracks_df, [SAMPLE_AUDIO_FEATURE])
        assert result.iloc[0]["danceability"] == pytest.approx(0.7)
        assert result.iloc[0]["tempo"] == pytest.approx(120.0)
        assert result.iloc[0]["valence"] == pytest.approx(0.65)

    def test_unmatched_track_gets_null_features(self):
        # track002 has no matching audio feature (only track001 does)
        tracks_df = tracks_from_raw([SAMPLE_TRACK_2])
        result = merge_audio_features(tracks_df, [SAMPLE_AUDIO_FEATURE])
        assert pd.isna(result.iloc[0]["danceability"])

    def test_empty_features_returns_df_unchanged(self):
        tracks_df = tracks_from_raw([SAMPLE_TRACK])
        result = merge_audio_features(tracks_df, [])
        assert pd.isna(result.iloc[0]["valence"])
        assert "track_id" in result.columns

    def test_none_items_in_features_are_skipped(self):
        tracks_df = tracks_from_raw([SAMPLE_TRACK])
        result = merge_audio_features(tracks_df, [None, None])
        assert pd.isna(result.iloc[0]["danceability"])

    def test_track_metadata_preserved_after_merge(self):
        tracks_df = tracks_from_raw([SAMPLE_TRACK])
        result = merge_audio_features(tracks_df, [SAMPLE_AUDIO_FEATURE])
        assert result.iloc[0]["name"] == "Test Track"
        assert result.iloc[0]["popularity"] == 75


class TestArtistsFromRaw:
    def test_basic_fields(self):
        df = artists_from_raw([SAMPLE_ARTIST])
        assert df.iloc[0]["artist_id"] == "artist001"
        assert df.iloc[0]["name"] == "Test Artist"
        assert df.iloc[0]["followers"] == 500_000

    def test_genres_list(self):
        df = artists_from_raw([SAMPLE_ARTIST])
        assert df.iloc[0]["genres"] == ["indie pop", "dream pop"]

    def test_deduplicates(self):
        df = artists_from_raw([SAMPLE_ARTIST, SAMPLE_ARTIST])
        assert len(df) == 1


class TestArtistsFromTracks:
    def test_extracts_all_artists_from_track(self):
        df = artists_from_tracks([SAMPLE_TRACK_2])
        assert set(df["artist_id"]) == {"artist001", "artist002"}

    def test_handles_wrapped_envelope(self):
        df = artists_from_tracks([SAMPLE_SAVED_TRACK_ITEM])
        assert df.iloc[0]["artist_id"] == "artist001"

    def test_empty_genres_for_track_artists(self):
        df = artists_from_tracks([SAMPLE_TRACK])
        assert df.iloc[0]["genres"] == []


class TestTopTracksTable:
    def test_rank_is_one_indexed(self):
        df = top_tracks_table([SAMPLE_TRACK, SAMPLE_TRACK_2], "short_term")
        assert df.iloc[0]["rank"] == 1
        assert df.iloc[1]["rank"] == 2

    def test_time_range_column(self):
        df = top_tracks_table([SAMPLE_TRACK], "long_term")
        assert df.iloc[0]["time_range"] == "long_term"

    def test_track_id_column(self):
        df = top_tracks_table([SAMPLE_TRACK], "short_term")
        assert df.iloc[0]["track_id"] == "track001"

    def test_captured_at_is_set(self):
        df = top_tracks_table([SAMPLE_TRACK], "short_term")
        assert pd.notna(df.iloc[0]["captured_at"])


class TestTopArtistsTable:
    def test_rank_and_artist_id(self):
        df = top_artists_table([SAMPLE_ARTIST], "medium_term")
        assert df.iloc[0]["artist_id"] == "artist001"
        assert df.iloc[0]["rank"] == 1


class TestRecentlyPlayedTable:
    def test_track_id_and_timestamp(self):
        df = recently_played_table([SAMPLE_RECENTLY_PLAYED_ITEM])
        assert df.iloc[0]["track_id"] == "track001"
        assert pd.notna(df.iloc[0]["played_at"])

    def test_deduplicates_by_track_and_time(self):
        df = recently_played_table([
            SAMPLE_RECENTLY_PLAYED_ITEM,
            SAMPLE_RECENTLY_PLAYED_ITEM,
        ])
        assert len(df) == 1


class TestSavedTracksTable:
    def test_track_id_and_added_at(self):
        df = saved_tracks_table([SAMPLE_SAVED_TRACK_ITEM])
        assert df.iloc[0]["track_id"] == "track002"
        assert pd.notna(df.iloc[0]["added_at"])

    def test_deduplicates(self):
        df = saved_tracks_table([SAMPLE_SAVED_TRACK_ITEM, SAMPLE_SAVED_TRACK_ITEM])
        assert len(df) == 1
