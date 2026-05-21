import os

import spotipy
from dotenv import load_dotenv
from spotipy.oauth2 import SpotifyOAuth

load_dotenv()

# All scopes needed across the entire project.
SCOPES = " ".join([
    "user-top-read",
    "user-library-read",
    "user-read-recently-played",
])


def get_spotify_client() -> spotipy.Spotify:
    """Return an authenticated Spotify client using the Authorization Code flow.

    First run: opens a browser tab for you to approve the app, then prompts you
    to paste the redirect URL back into the terminal. The token is cached in
    .cache so all subsequent runs are silent.
    """
    auth_manager = SpotifyOAuth(
        client_id=os.environ["SPOTIPY_CLIENT_ID"],
        client_secret=os.environ["SPOTIPY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIPY_REDIRECT_URI"],
        scope=SCOPES,
        cache_path=".cache",
        open_browser=False,
    )
    return spotipy.Spotify(auth_manager=auth_manager)
