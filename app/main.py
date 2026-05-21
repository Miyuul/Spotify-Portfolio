import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import duckdb
from pathlib import Path
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# ── Constants ────────────────────────────────────────────────────────────────
DB_PATH = Path("data/spotify.duckdb")

TIME_RANGE_LABELS = {
    "short_term":  "Last 4 Weeks",
    "medium_term": "Last 6 Months",
    "long_term":   "All Time",
}

# Features used for the radar chart (all already on a 0–1 scale)
RADAR_FEATURES = [
    "danceability", "energy", "valence",
    "acousticness", "speechiness", "instrumentalness", "liveness",
]

# Features used for k-means clustering (tempo added for tempo-driven variation)
CLUSTER_FEATURES = [
    "danceability", "energy", "valence",
    "acousticness", "instrumentalness", "tempo",
]

N_CLUSTERS = 4

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Spotify Dashboard",
    page_icon="🎵",
    layout="wide",
)

# ── DB connection (shared across reruns via cache_resource) ──────────────────
@st.cache_resource
def _conn() -> duckdb.DuckDBPyConnection | None:
    if not DB_PATH.exists():
        return None
    return duckdb.connect(str(DB_PATH), read_only=True)


# ── Queries (cached for 1 hour; invalidated by the sidebar refresh button) ───
@st.cache_data(ttl=3600)
def q_top_artists(time_range: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT a.name, ta.rank
        FROM top_artists ta
        JOIN artists a ON ta.artist_id = a.artist_id
        WHERE ta.time_range = ?
        ORDER BY ta.rank
        """,
        [time_range],
    ).df()


@st.cache_data(ttl=3600)
def q_top_tracks(time_range: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT tt.rank,
               t.name,
               t.artist_names[1] AS primary_artist,
               COALESCE(a.genres[1], '—') AS genre,
               t.duration_ms
        FROM top_tracks tt
        JOIN tracks t ON tt.track_id = t.track_id
        LEFT JOIN artists a ON a.artist_id = t.artist_ids[1]
        WHERE tt.time_range = ?
        ORDER BY tt.rank
        """,
        [time_range],
    ).df()


@st.cache_data(ttl=3600)
def q_top_genres(time_range: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT genre, COUNT(*) AS count
        FROM (
            SELECT unnest(a.genres) AS genre
            FROM top_artists ta
            JOIN artists a ON ta.artist_id = a.artist_id
            WHERE ta.time_range = ?
        )
        GROUP BY genre
        ORDER BY count DESC
        LIMIT 15
        """,
        [time_range],
    ).df()


@st.cache_data(ttl=3600)
def q_release_eras(time_range: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT
            CASE
                WHEN CAST(SUBSTRING(t.release_date, 1, 4) AS INTEGER) < 1980 THEN 'Pre-1980'
                WHEN CAST(SUBSTRING(t.release_date, 1, 4) AS INTEGER) < 1990 THEN '1980s'
                WHEN CAST(SUBSTRING(t.release_date, 1, 4) AS INTEGER) < 2000 THEN '1990s'
                WHEN CAST(SUBSTRING(t.release_date, 1, 4) AS INTEGER) < 2010 THEN '2000s'
                WHEN CAST(SUBSTRING(t.release_date, 1, 4) AS INTEGER) < 2020 THEN '2010s'
                ELSE '2020s'
            END AS era,
            COUNT(*) AS count
        FROM top_tracks tt
        JOIN tracks t ON tt.track_id = t.track_id
        WHERE tt.time_range = ?
          AND t.release_date IS NOT NULL
          AND LENGTH(t.release_date) >= 4
        GROUP BY era
        ORDER BY era
        """,
        [time_range],
    ).df()


@st.cache_data(ttl=3600)
def q_audio_features(time_range: str) -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT t.danceability, t.energy, t.valence, t.acousticness,
               t.speechiness, t.instrumentalness, t.liveness
        FROM top_tracks tt
        JOIN tracks t ON tt.track_id = t.track_id
        WHERE tt.time_range = ?
          AND t.danceability IS NOT NULL
        """,
        [time_range],
    ).df()


@st.cache_data(ttl=3600)
def q_is_demo() -> bool:
    conn = _conn()
    if conn is None:
        return False
    try:
        row = conn.execute("SELECT COUNT(*) FROM tracks WHERE is_demo = TRUE").fetchone()
        return row[0] > 0
    except Exception:
        return False


@st.cache_data(ttl=3600)
def q_all_tracks_with_features() -> pd.DataFrame:
    conn = _conn()
    if conn is None:
        return pd.DataFrame()
    return conn.execute(
        """
        SELECT track_id,
               name,
               artist_names[1] AS primary_artist,
               danceability, energy, valence,
               acousticness, speechiness, instrumentalness,
               liveness, tempo
        FROM tracks
        WHERE danceability IS NOT NULL
        """,
    ).df()


# ── Clustering helpers ────────────────────────────────────────────────────────
def _cluster_label(row: pd.Series) -> str:
    """Name a cluster from its mean audio-feature values (original scale)."""
    energy    = row.get("energy", 0)
    valence   = row.get("valence", 0)
    acousticness = row.get("acousticness", 0)
    if energy >= 0.6 and valence >= 0.5:
        return "Upbeat & Energetic"
    if energy >= 0.6 and valence < 0.5:
        return "Dark & Intense"
    if energy < 0.6 and acousticness >= 0.4:
        return "Acoustic & Mellow"
    return "Chill & Introspective"


def _describe_component(component: np.ndarray, feature_names: list[str]) -> str:
    """Return a short axis label from the two features with the largest PCA loadings."""
    abs_load = np.abs(component)
    top_idx = np.argsort(abs_load)[::-1][:2]
    parts = []
    for i in top_idx:
        direction = "↑" if component[i] > 0 else "↓"
        parts.append(f"{direction} {feature_names[i].replace('_', ' ').title()}")
    return "  ·  ".join(parts)


def run_clustering(df: pd.DataFrame) -> tuple[pd.DataFrame, str, str]:
    """Attach cluster labels and 2-D PCA coordinates to a tracks DataFrame.

    Returns (enriched_df, pc1_axis_label, pc2_axis_label).
    """
    X = df[CLUSTER_FEATURES].dropna()
    idx = X.index

    scaler   = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    km = KMeans(n_clusters=N_CLUSTERS, random_state=42, n_init="auto")
    labels = km.fit_predict(X_scaled)

    pca    = PCA(n_components=2, random_state=42)
    coords = pca.fit_transform(X_scaled)

    pc1_label = _describe_component(pca.components_[0], CLUSTER_FEATURES)
    pc2_label = _describe_component(pca.components_[1], CLUSTER_FEATURES)

    # Name clusters using original-scale centroids so thresholds make sense.
    centroids_orig = scaler.inverse_transform(km.cluster_centers_)
    centroid_df    = pd.DataFrame(centroids_orig, columns=CLUSTER_FEATURES)

    # Disambiguate if two clusters get the same auto-label.
    used: dict[str, int] = {}
    name_map: dict[int, str] = {}
    for i in range(N_CLUSTERS):
        name = _cluster_label(centroid_df.iloc[i])
        if name in used:
            used[name] += 1
            name = f"{name} ({used[name]})"
        else:
            used[name] = 1
        name_map[i] = name

    result = df.loc[idx].copy()
    result["cluster_id"] = labels
    result["cluster"]    = result["cluster_id"].map(name_map)
    result["pc1"]        = coords[:, 0]
    result["pc2"]        = coords[:, 1]
    return result, pc1_label, pc2_label


# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Controls")
    time_range = st.selectbox(
        "Time range",
        options=list(TIME_RANGE_LABELS.keys()),
        format_func=lambda k: TIME_RANGE_LABELS[k],
    )
    if st.button("Clear cache & refresh"):
        st.cache_data.clear()
        st.rerun()
    st.caption(
        "**Short term** ≈ last 4 weeks  \n"
        "**Medium term** ≈ last 6 months  \n"
        "**Long term** ≈ all time"
    )

# ── Guard: no data yet ────────────────────────────────────────────────────────
if not DB_PATH.exists():
    st.error(
        "**No data found.** Run the ingestion pipeline first:\n\n"
        "```\nuv run python -m src.pipeline\n```\n\n"
        "Then reload this page."
    )
    st.stop()

st.title("🎵 My Spotify Listening Dashboard")

tab_overview, tab_features, tab_map = st.tabs(
    ["📊 Overview", "🎛️ Audio Features", "🗺️ Taste Map"]
)


# ── Tab 1: Overview ───────────────────────────────────────────────────────────
with tab_overview:
    artists_df = q_top_artists(time_range)
    tracks_df  = q_top_tracks(time_range)
    genres_df  = q_top_genres(time_range)
    eras_df    = q_release_eras(time_range)

    col_a, col_b = st.columns(2)

    with col_a:
        st.subheader("Top Artists")
        st.caption("Your most-listened-to artists for the selected time range. Rank #1 is at the top.")
        if not artists_df.empty:
            plot_df = artists_df.head(20).copy()
            plot_df["score"] = len(plot_df) + 1 - plot_df["rank"]
            plot_df = plot_df.sort_values("rank", ascending=False)  # rank 1 ends up at top

            fig = px.bar(
                plot_df,
                y="name",
                x="score",
                orientation="h",
                color="score",
                color_continuous_scale=[[0, "#a7f3d0"], [1, "#059669"]],
                text="rank",
                labels={"name": "", "score": ""},
            )
            fig.update_traces(
                texttemplate="  #%{text}",
                textposition="inside",
                textfont=dict(color="white", size=12, family="Arial Black"),
            )
            fig.update_coloraxes(showscale=False)
            fig.update_layout(
                template="plotly_white",
                xaxis=dict(showticklabels=False, showgrid=False, zeroline=False, title=""),
                yaxis=dict(title="", tickfont=dict(size=13)),
                margin=dict(l=10, r=20, t=10, b=10),
                height=520,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No artist data yet.")

    with col_b:
        st.subheader("Top Genres")
        st.caption(
            "Genres of your top artists, sourced from Last.fm tags. "
            "Each bar counts how many of your top artists belong to that genre."
        )
        if not genres_df.empty:
            plot_df = genres_df.sort_values("count")
            fig = px.bar(
                plot_df,
                y="genre",
                x="count",
                orientation="h",
                color="count",
                color_continuous_scale=[[0, "#ddd6fe"], [1, "#7c3aed"]],
                text="count",
                labels={"genre": "", "count": "Artists in genre"},
            )
            fig.update_traces(textposition="outside", textfont=dict(size=12))
            fig.update_coloraxes(showscale=False)
            fig.update_layout(
                template="plotly_white",
                xaxis=dict(
                    title="Number of your top artists who play this genre",
                    showgrid=True, gridcolor="#f3f4f6",
                ),
                yaxis=dict(title="", tickfont=dict(size=12)),
                margin=dict(l=10, r=50, t=10, b=10),
                height=520,
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Run `uv run python -m src.enrich` to load genre data from Last.fm.")

    st.subheader("Music Eras")
    st.caption(
        "Which decades do your top tracks come from? "
        "Shows whether your taste leans towards new releases or older music."
    )
    if not eras_df.empty:
        fig = px.bar(
            eras_df,
            x="era",
            y="count",
            color="count",
            color_continuous_scale=[[0, "#ddd6fe"], [1, "#7c3aed"]],
            text="count",
            labels={"era": "Decade", "count": "Number of top tracks"},
        )
        fig.update_traces(textposition="outside", textfont=dict(size=13))
        fig.update_coloraxes(showscale=False)
        fig.update_layout(
            template="plotly_white",
            xaxis=dict(title="Decade", tickfont=dict(size=13)),
            yaxis=dict(title="Number of your top tracks from this decade", gridcolor="#f3f4f6"),
            margin=dict(l=10, r=20, t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Top Tracks")
    st.caption("Your top 50 tracks for the selected period, ranked by how much you listened to them.")
    if not tracks_df.empty:
        display = tracks_df.copy()
        display["duration_ms"] = (display["duration_ms"] / 1000).round(0).astype("Int64").apply(
            lambda s: f"{s // 60}:{s % 60:02d}" if pd.notna(s) else ""
        )
        display = display.rename(columns={
            "rank": "#",
            "name": "Track",
            "primary_artist": "Artist",
            "genre": "Genre",
            "duration_ms": "Duration",
        })
        st.dataframe(display, use_container_width=True, hide_index=True)
    else:
        st.info("No track data yet.")


# ── Tab 2: Audio Features ─────────────────────────────────────────────────────
with tab_features:
    st.subheader("Your Audio Feature Profile")
    st.caption(
        "Each axis shows the average value (0–1) across your top tracks. "
        "**Danceability**: rhythmic suitability for dancing. "
        "**Energy**: intensity and activity level. "
        "**Valence**: musical positivity — high = cheerful, low = melancholic. "
        "**Acousticness**: likelihood the track uses acoustic instruments. "
        "**Speechiness**: presence of spoken words. "
        "**Instrumentalness**: absence of vocals. "
        "**Liveness**: presence of a live audience."
    )

    feature_data = {tr: q_audio_features(tr) for tr in TIME_RANGE_LABELS}
    has_features = any(not df.empty for df in feature_data.values())

    if not has_features:
        st.warning(
            "No audio feature data found — the Spotify API likely returned a 403. "
            "See the README for instructions on requesting extended quota access."
        )
    else:
        if q_is_demo():
            st.warning(
                "⚠️ **Demo data** — audio features are synthetically generated using "
                "realistic statistical distributions. The Spotify `audio-features` endpoint "
                "is unavailable for Development Mode apps. The pipeline and visualisations "
                "are production-ready; real data would populate automatically with API access."
            )

        # Heatmap: features × time ranges — each cell shows the mean score (0–1).
        st.subheader("Feature Heatmap — All Time Ranges")
        st.caption(
            "Each cell is the average score (0–1) across your top 50 tracks for that period. "
            "Red = low · Yellow = medium · Green = high."
        )
        heat_rows = []
        for tr, tr_label in TIME_RANGE_LABELS.items():
            feat_df = feature_data[tr]
            if feat_df.empty:
                continue
            row = {"Time Range": tr_label}
            for col in RADAR_FEATURES:
                row[col.replace("_", " ").title()] = round(feat_df[col].mean(), 3)
            heat_rows.append(row)

        if heat_rows:
            heat_df = pd.DataFrame(heat_rows).set_index("Time Range")
            fig_heat = px.imshow(
                heat_df,
                color_continuous_scale="RdYlGn",
                zmin=0,
                zmax=1,
                text_auto=".2f",
                labels={"x": "Audio Feature", "y": "Time Range", "color": "Avg Score"},
                aspect="auto",
            )
            fig_heat.update_traces(textfont=dict(size=15))
            fig_heat.update_layout(
                coloraxis_colorbar=dict(
                    title="Score",
                    tickvals=[0, 0.25, 0.5, 0.75, 1.0],
                    ticktext=["0.00", "0.25", "0.50", "0.75", "1.00"],
                    len=0.8,
                ),
                margin=dict(t=10, b=20, l=10, r=10),
                height=220,
                xaxis=dict(tickfont=dict(size=13)),
                yaxis=dict(tickfont=dict(size=13)),
            )
            st.plotly_chart(fig_heat, use_container_width=True)

        st.subheader(f"Feature Breakdown — {TIME_RANGE_LABELS[time_range]}")
        st.caption(
            "Average score for each audio feature across your top tracks in the selected period. "
            "Colour shows low (red) → medium (yellow) → high (green)."
        )
        feat_df = feature_data[time_range]
        if not feat_df.empty:
            means_df = feat_df[RADAR_FEATURES].mean().reset_index()
            means_df.columns = ["feature", "mean"]
            means_df["feature"] = means_df["feature"].str.replace("_", " ").str.title()
            fig_bar = px.bar(
                means_df,
                x="feature",
                y="mean",
                color="mean",
                color_continuous_scale=[
                    [0.0, "#fca5a5"],
                    [0.4, "#fde68a"],
                    [0.7, "#86efac"],
                    [1.0, "#16a34a"],
                ],
                range_y=[0, 1.2],
                text="mean",
                labels={"feature": "", "mean": "Average score (0–1)"},
            )
            fig_bar.update_traces(
                texttemplate="%{text:.2f}",
                textposition="outside",
                textfont=dict(size=13),
            )
            fig_bar.update_coloraxes(showscale=False)
            fig_bar.update_layout(
                template="plotly_white",
                yaxis=dict(
                    title="Average score  (0 = low  ·  1 = high)",
                    range=[0, 1.25],
                    gridcolor="#f3f4f6",
                ),
                xaxis=dict(tickfont=dict(size=13)),
                margin=dict(t=20, b=10),
            )
            st.plotly_chart(fig_bar, use_container_width=True)


# ── Tab 3: Taste Map ──────────────────────────────────────────────────────────
with tab_map:
    st.subheader("Your Taste Map")
    st.caption(
        "Each dot is a track from your library. "
        "Tracks are grouped into **four mood clusters** using k-means on six audio features "
        "(danceability, energy, valence, acousticness, instrumentalness, tempo). "
        "The axes are the top two principal components from PCA — each axis label shows the "
        "two audio features that drive it most (↑ = positive loading, ↓ = negative loading). "
        "Hover over any dot to see track details."
    )

    all_tracks = q_all_tracks_with_features()

    if q_is_demo():
        st.warning(
            "⚠️ **Demo data** — cluster positions are based on synthetically generated "
            "audio features, not your real listening data. Track names and artists are real."
        )

    if all_tracks.empty:
        st.warning(
            "No tracks with audio features found. "
            "Run the ingestion pipeline with audio-feature access enabled (see README)."
        )
    elif len(all_tracks) < N_CLUSTERS:
        st.warning(
            f"Need at least {N_CLUSTERS} tracks with audio features to cluster. "
            f"Found {len(all_tracks)}."
        )
    else:
        clustered, pc1_label, pc2_label = run_clustering(all_tracks)

        fig_scatter = px.scatter(
            clustered,
            x="pc1",
            y="pc2",
            color="cluster",
            color_discrete_sequence=px.colors.qualitative.Bold,
            hover_data={
                "name": True,
                "primary_artist": True,
                "energy": ":.2f",
                "valence": ":.2f",
                "danceability": ":.2f",
                "pc1": False,
                "pc2": False,
                "cluster_id": False,
                "cluster": False,
            },
            labels={
                "pc1": pc1_label,
                "pc2": pc2_label,
                "cluster": "Mood Cluster",
                "name": "Track",
                "primary_artist": "Artist",
                "energy": "Energy",
                "valence": "Mood (Valence)",
                "danceability": "Danceability",
            },
            opacity=0.82,
            height=580,
        )
        fig_scatter.update_traces(
            marker=dict(size=8, line=dict(width=0.8, color="white")),
        )
        fig_scatter.update_layout(
            template="plotly_white",
            legend=dict(
                orientation="h",
                y=-0.18,
                title="Mood Cluster",
                font=dict(size=13),
            ),
            xaxis=dict(
                zeroline=True, zerolinecolor="#e5e7eb",
                gridcolor="#f3f4f6", tickfont=dict(size=10, color="#9ca3af"),
            ),
            yaxis=dict(
                zeroline=True, zerolinecolor="#e5e7eb",
                gridcolor="#f3f4f6", tickfont=dict(size=10, color="#9ca3af"),
            ),
            margin=dict(t=20, b=100, l=10, r=10),
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

        st.subheader("Cluster Summary")
        st.caption(
            "Mean audio-feature values per cluster. "
            "High **valence** + high **energy** → upbeat. "
            "Low **energy** + high **acousticness** → mellow acoustic. "
            "Low **instrumentalness** → vocal-heavy."
        )
        summary = (
            clustered
            .groupby("cluster")[CLUSTER_FEATURES]
            .mean()
            .round(3)
            .reset_index()
        )
        summary.columns = [c.replace("_", " ").title() for c in summary.columns]
        st.dataframe(summary, use_container_width=True, hide_index=True)
