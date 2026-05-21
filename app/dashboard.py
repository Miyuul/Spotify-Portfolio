"""
Spotify Portfolio — live OAuth app.

Anyone can log in with their own Spotify account to see their personal music
portfolio. No data is stored on the server beyond the current browser session.

Run:
    uv run streamlit run app/dashboard.py

Required in .env (server-side only — each visitor authenticates themselves):
    SPOTIPY_CLIENT_ID      — from https://developer.spotify.com/dashboard
    SPOTIPY_CLIENT_SECRET  — from https://developer.spotify.com/dashboard
    SPOTIPY_REDIRECT_URI   — must match a URI registered in your Spotify app
                             e.g. http://localhost:8501 for local development
"""
from __future__ import annotations

import os
from collections import Counter

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import spotipy
import streamlit as st
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()


def _secret(key: str) -> str:
    """Read from st.secrets (Streamlit Cloud) with fallback to os.environ (local)."""
    try:
        return st.secrets[key]
    except (KeyError, FileNotFoundError):
        return os.environ.get(key, "")


_SCOPES = " ".join([
    "user-top-read",
    "user-library-read",
    "user-read-recently-played",
])

_RANGE_LABELS = {
    "short_term":  "Last 4 weeks",
    "medium_term": "Last 6 months",
    "long_term":   "All time",
}

_AUDIO_FEATURES = [
    "danceability", "energy", "valence",
    "acousticness", "speechiness", "instrumentalness", "liveness",
]


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

def _make_auth_manager() -> SpotifyOAuth:
    client_id     = _secret("SPOTIPY_CLIENT_ID")
    client_secret = _secret("SPOTIPY_CLIENT_SECRET")
    redirect_uri  = _secret("SPOTIPY_REDIRECT_URI")

    missing = [k for k, v in [
        ("SPOTIPY_CLIENT_ID", client_id),
        ("SPOTIPY_CLIENT_SECRET", client_secret),
        ("SPOTIPY_REDIRECT_URI", redirect_uri),
    ] if not v]
    if missing:
        st.error(
            f"Missing secret(s): {', '.join(missing)}. "
            "Add them in Streamlit Cloud → app Settings → Secrets."
        )
        st.stop()

    return SpotifyOAuth(
        client_id=client_id,
        client_secret=client_secret,
        redirect_uri=redirect_uri,
        scope=_SCOPES,
        cache_path=None,
        show_dialog=False,
    )


def _get_sp() -> spotipy.Spotify | None:
    """Return a valid Spotify client from session state, refreshing the token if needed."""
    token_info = st.session_state.get("token_info")
    if not token_info:
        return None
    mgr = _make_auth_manager()
    if mgr.is_token_expired(token_info):
        token_info = mgr.refresh_access_token(token_info["refresh_token"])
        st.session_state["token_info"] = token_info
    return spotipy.Spotify(auth=token_info["access_token"])


# ---------------------------------------------------------------------------
# Data fetching — stored in session_state so each user only sees their own data
# ---------------------------------------------------------------------------

def _fetch_all(sp: spotipy.Spotify) -> None:
    data: dict = {}

    with st.spinner("Loading your music data…"):
        for tr in _RANGE_LABELS:
            data[f"top_tracks_{tr}"]  = sp.current_user_top_tracks(limit=50, time_range=tr)["items"]
            data[f"top_artists_{tr}"] = sp.current_user_top_artists(limit=50, time_range=tr)["items"]

        data["recently_played"] = sp.current_user_recently_played(limit=50)["items"]

        # Deduplicate track IDs across all time ranges then batch-fetch audio features.
        all_ids = list({item["id"] for tr in _RANGE_LABELS for item in data[f"top_tracks_{tr}"]})
        features: dict[str, dict] = {}
        try:
            for i in range(0, len(all_ids), 100):
                for f in (sp.audio_features(all_ids[i : i + 100]) or []):
                    if f:
                        features[f["id"]] = f
        except spotipy.SpotifyException as exc:
            if exc.http_status != 403:
                raise
            # 403 means the app lacks extended quota access; charts will note this.
        data["audio_features"] = features

    st.session_state["data"] = data


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def _artist_names(artists: list[dict]) -> str:
    return ", ".join(a["name"] for a in artists)


def _pct(val) -> str:
    return f"{val:.0%}" if pd.notna(val) else "—"


def _tracks_df(time_range: str) -> pd.DataFrame:
    features = st.session_state["data"]["audio_features"]
    rows = []
    for rank, item in enumerate(st.session_state["data"][f"top_tracks_{time_range}"], 1):
        f = features.get(item["id"]) or {}
        rows.append({
            "#":          rank,
            "Track":      item["name"],
            "Artists":    _artist_names(item.get("artists", [])),
            "Album":      item.get("album", {}).get("name", ""),
            "Popularity": item.get("popularity"),
            **{feat: f.get(feat) for feat in _AUDIO_FEATURES},
            "tempo":      f.get("tempo"),
        })
    return pd.DataFrame(rows)


def _artists_df(time_range: str) -> pd.DataFrame:
    rows = []
    for rank, item in enumerate(st.session_state["data"][f"top_artists_{time_range}"], 1):
        genres    = item.get("genres", [])
        followers = item.get("followers", {}).get("total")
        rows.append({
            "#":          rank,
            "Artist":     item["name"],
            "Genres":     ", ".join(genres[:3]) if genres else "—",
            "Popularity": item.get("popularity"),
            "Followers":  f"{followers:,}" if followers is not None else "—",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.set_page_config(page_title="Music Portfolio", page_icon="🎵", layout="wide")

# Handle Spotify OAuth callback (?code=... or ?error=...)
code  = st.query_params.get("code")
error = st.query_params.get("error")

if error:
    st.error(f"Spotify login declined: {error}")
elif code and "token_info" not in st.session_state:
    mgr = _make_auth_manager()
    st.session_state["token_info"] = mgr.get_access_token(code, check_cache=False)
    st.query_params.clear()
    st.rerun()

sp = _get_sp()

# ── Login screen ────────────────────────────────────────────────────────────
if sp is None:
    st.title("Music Portfolio")
    st.write("Log in with your Spotify account to explore your personal music portfolio.")
    mgr = _make_auth_manager()
    st.link_button("Log in with Spotify", mgr.get_authorize_url(), type="primary")
    st.stop()

# ── Load data once per session ───────────────────────────────────────────────
if "data" not in st.session_state:
    _fetch_all(sp)

# ── Header ───────────────────────────────────────────────────────────────────
title_col, logout_col = st.columns([9, 1])
title_col.title("Music Portfolio")
if logout_col.button("Log out", use_container_width=True):
    st.session_state.clear()
    st.rerun()

# ── Tabs ─────────────────────────────────────────────────────────────────────
tab_tracks, tab_artists, tab_genres, tab_vibes, tab_history = st.tabs([
    "Top Tracks", "Top Artists", "Genres", "Audio Vibes", "Recent Plays",
])


# ── Top Tracks ───────────────────────────────────────────────────────────────
with tab_tracks:
    tr = st.segmented_control(
        "Time range", list(_RANGE_LABELS), format_func=_RANGE_LABELS.get,
        default="medium_term", key="tr_tracks",
    )
    df = _tracks_df(tr)
    st.dataframe(
        df[["#", "Track", "Artists", "Album", "Popularity"]],
        use_container_width=True, hide_index=True,
    )


# ── Top Artists ──────────────────────────────────────────────────────────────
with tab_artists:
    tr = st.segmented_control(
        "Time range", list(_RANGE_LABELS), format_func=_RANGE_LABELS.get,
        default="medium_term", key="tr_artists",
    )
    st.dataframe(_artists_df(tr), use_container_width=True, hide_index=True)


# ── Genres ───────────────────────────────────────────────────────────────────
with tab_genres:
    tr = st.segmented_control(
        "Time range", list(_RANGE_LABELS), format_func=_RANGE_LABELS.get,
        default="medium_term", key="tr_genres",
    )
    counts = Counter(
        g
        for item in st.session_state["data"][f"top_artists_{tr}"]
        for g in item.get("genres", [])
    )
    if counts:
        gdf = pd.DataFrame(counts.most_common(25), columns=["genre", "count"])
        fig = px.bar(
            gdf, x="count", y="genre", orientation="h",
            labels={"count": "Artists", "genre": ""},
            color="count", color_continuous_scale="Greens",
        )
        fig.update_layout(yaxis=dict(autorange="reversed"), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No genre data available for your top artists in this time range.")


# ── Audio Vibes ──────────────────────────────────────────────────────────────
with tab_vibes:
    tr = st.segmented_control(
        "Time range", list(_RANGE_LABELS), format_func=_RANGE_LABELS.get,
        default="medium_term", key="tr_vibes",
    )
    df = _tracks_df(tr)
    has_features = df[_AUDIO_FEATURES].notna().any().any()

    if not has_features:
        st.info(
            "Audio features are unavailable — your Spotify app may need extended "
            "quota access. See https://developer.spotify.com/documentation/web-api/concepts/quota-modes"
        )
    else:
        avgs = df[_AUDIO_FEATURES].mean()
        vals = avgs.tolist()
        fig = go.Figure(go.Scatterpolar(
            r=vals + [vals[0]],
            theta=_AUDIO_FEATURES + [_AUDIO_FEATURES[0]],
            fill="toself",
            line_color="#1DB954",
            fillcolor="rgba(29,185,84,0.25)",
            name="",
        ))
        fig.update_layout(
            polar=dict(radialaxis=dict(visible=True, range=[0, 1])),
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)

        for col, feat in zip(st.columns(len(_AUDIO_FEATURES)), _AUDIO_FEATURES):
            col.metric(feat.capitalize(), _pct(avgs[feat]))

    st.divider()
    st.subheader("Tempo distribution")
    if has_features and df["tempo"].notna().any():
        fig2 = px.histogram(
            df.dropna(subset=["tempo"]), x="tempo", nbins=20,
            labels={"tempo": "BPM"}, color_discrete_sequence=["#1DB954"],
        )
        st.plotly_chart(fig2, use_container_width=True)


# ── Recent Plays ─────────────────────────────────────────────────────────────
with tab_history:
    items = st.session_state["data"]["recently_played"]
    rows = [
        {
            "Played At": pd.to_datetime(it["played_at"]).strftime("%b %d, %Y  %H:%M"),
            "Track":     it["track"]["name"],
            "Artists":   _artist_names(it["track"].get("artists", [])),
        }
        for it in items
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    if rows:
        st.divider()
        st.subheader("Plays by hour of day")
        hours = pd.to_datetime([it["played_at"] for it in items]).hour
        hdf = (
            pd.Series(hours, name="hour")
            .value_counts()
            .rename_axis("hour")
            .reset_index(name="plays")
            .sort_values("hour")
        )
        fig3 = px.bar(
            hdf, x="hour", y="plays",
            labels={"hour": "Hour of Day", "plays": "Plays"},
            color_discrete_sequence=["#1DB954"],
        )
        st.plotly_chart(fig3, use_container_width=True)
