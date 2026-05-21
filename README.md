# Spotify Music Portfolio

An interactive dashboard that lets you explore your personal Spotify listening history — your top tracks, top artists, genre breakdown, audio features, and recent play history.

## How to use it

1. Open the app
2. Click **Log in with Spotify**
3. Approve access when Spotify asks
4. Your portfolio loads automatically

That's it. No account setup required beyond your existing Spotify account.

## Running locally

**Prerequisites:** Python 3.11+ and [uv](https://docs.astral.sh/uv/getting-started/installation/)

1. Clone the repo and install dependencies:

   ```bash
   git clone https://github.com/Miyuul/Spotify-Portfolio.git
   cd Spotify-Portfolio
   uv sync
   ```

2. Copy the example env file and fill in your Spotify credentials:

   ```bash
   cp .env.example .env
   ```

   Open `.env` and add your `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, and set:

   ```env
   SPOTIPY_REDIRECT_URI=http://localhost:8501
   ```

   You can get your credentials from [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard). Make sure `http://localhost:8501` is added as a Redirect URI in your Spotify app settings.

3. Run the app:

   ```bash
   uv run streamlit run app/dashboard.py
   ```

4. Open [http://localhost:8501](http://localhost:8501) in your browser and log in with Spotify.

## Notes

- Your data is never stored — it's fetched fresh each time you log in and exists only for your session
- Click **Log out** when you're done to clear your session
- Audio feature charts (danceability, energy, valence, etc.) may not appear for all accounts depending on Spotify API access
