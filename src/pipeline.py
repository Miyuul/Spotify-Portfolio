"""CLI entry point for the ingestion pipeline.

Usage:
    uv run python -m src.pipeline
    # or with an activated venv:
    python -m src.pipeline
"""
import logging

from .auth import get_spotify_client
from .ingest import run

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)

if __name__ == "__main__":
    sp = get_spotify_client()
    run(sp)
