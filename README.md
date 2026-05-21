# Spotify Listening Dashboard

An interactive music portfolio: anyone can log in with their own Spotify account to explore
their personal listening history — top tracks, top artists, genre breakdown, audio features,
and recent play history. No data is stored on the server beyond the current browser session.

---

## 1. Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended) **or** pip + virtualenv

---

## 2. Get Spotify API Credentials

You need a free Spotify developer app — no approval required for personal use.

### Step-by-step

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and log in
   with your regular Spotify account.

2. Click **Create app** and fill in the form:
   - **App name:** anything, e.g. `My Portfolio Dashboard`
   - **App description:** anything
   - **Redirect URIs:** add exactly `http://localhost:8501` (Streamlit's default port)
   - Under "Which API/SDKs are you planning to use?" check **Web API**

3. Click **Save**.

4. On the app's page click **Settings**. You'll see:
   - **Client ID** — visible immediately
   - **Client Secret** — click "View client secret" to reveal it

5. Copy both values; you'll paste them into `.env` in the next step.

> **Note on audio features:** Spotify restricted the `audio-features` endpoint in late 2024.
> Apps in Development Mode (≤ 25 users) may get a `403` when fetching audio features.
> If that happens, ingestion still completes — audio-feature columns will be `NULL` in DuckDB.
> To restore access, submit a [quota extension request](https://developer.spotify.com/documentation/web-api/concepts/quota-modes)
> from your app's dashboard. The dashboard's feature-profile and taste-map sections require
> this data, so it's worth requesting.

---

## 3. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in your credentials:

```
SPOTIPY_CLIENT_ID=<your client id>
SPOTIPY_CLIENT_SECRET=<your client secret>
SPOTIPY_REDIRECT_URI=http://localhost:8501
```

---

## 4. Install Dependencies

### With uv (recommended)

```bash
uv sync                 # installs runtime deps
uv sync --extra dev     # also installs pytest
```

### With pip

```bash
python -m venv .venv
# Mac/Linux:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -e ".[dev]"
```

---

## 5. Run the Dashboard

```bash
uv run streamlit run app/dashboard.py
# or with an activated venv:
streamlit run app/dashboard.py
```

Open `http://localhost:8501` in a browser. Click **Log in with Spotify** — anyone with a
Spotify account can log in and see their own portfolio. Each visitor's data is fetched live
and stays in their browser session only.

> **Sharing with others:** deploy the app (e.g. [Streamlit Community Cloud](https://streamlit.io/cloud))
> and register your deployment URL as a Redirect URI in your Spotify app dashboard.
> Visitors only need a Spotify account — not your credentials.

---

## 6. Optional: Offline Ingestion Pipeline

The `src/pipeline.py` module pulls data into a local DuckDB file for offline analysis or
running your own private copy of the dashboard without re-authenticating each session.

```bash
uv run python -m src.pipeline
```

**First run only:** a browser tab opens for you to authorise. After clicking "Agree", Spotify
redirects to the redirect URI. Copy the full URL from your browser and paste it into the terminal.
The token is cached in `.cache` so all subsequent runs are silent.

---

## 7. Run Tests

```bash
uv run pytest       # or just: pytest
```

---

## Project Structure

```
├── src/
│   ├── auth.py         # Spotify OAuth client setup
│   ├── api.py          # Rate-limit-aware API call wrapper
│   ├── db.py           # DuckDB schema creation + upsert helpers
│   ├── transform.py    # Pure data-transformation functions (tested)
│   ├── ingest.py       # Ingestion orchestration: fetch → transform → load
│   └── pipeline.py     # CLI entry point
├── app/
│   └── dashboard.py    # Streamlit dashboard — live OAuth, multi-user
├── tests/
│   ├── conftest.py     # Shared fixture data
│   └── test_transform.py
├── data/               # gitignored — DuckDB file + raw JSON cache live here
│   └── .gitkeep
├── .env.example
├── pyproject.toml
└── README.md
```

---

## Data Model

| Table | Primary Key | Contents |
|---|---|---|
| `tracks` | `track_id` | Track metadata + audio features (danceability, energy, valence, …) |
| `artists` | `artist_id` | Artist name, genres, follower count |
| `top_tracks` | `(track_id, time_range)` | Your top-50 rank per time range (short/medium/long term) |
| `top_artists` | `(artist_id, time_range)` | Your top-50 artist rank per time range |
| `recently_played` | `(track_id, played_at)` | Last 50 plays with timestamps |
| `saved_tracks` | `track_id` | Your full liked-songs library |

Time ranges follow Spotify's naming: `short_term` ≈ 4 weeks, `medium_term` ≈ 6 months,
`long_term` ≈ all time.
