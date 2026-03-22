"""Configuration management — env vars with /data/settings.json overlay."""

import json
import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


DATA_DIR = Path(os.getenv("DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "settings.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: str = ""
    openrouter_model_primary: str = "google/gemini-flash-1.5"
    openrouter_model_secondary: str = "anthropic/claude-sonnet-4-5"
    llm_concurrency: int = 5
    auto_accept_threshold: float = 0.95
    port: int = 8080
    input_dir: str = "/input"
    output_dir: str = "/output"
    data_dir: str = str(DATA_DIR)


# Module-level singleton
settings = Settings()


def _overlay_from_file() -> None:
    """Overlay settings from the persisted JSON file if it exists."""
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            for key, value in data.items():
                if hasattr(settings, key):
                    setattr(settings, key, value)
        except (json.JSONDecodeError, OSError):
            pass


def save_settings() -> None:
    """Persist current settings to /data/settings.json."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "openrouter_api_key": settings.openrouter_api_key,
        "openrouter_model_primary": settings.openrouter_model_primary,
        "openrouter_model_secondary": settings.openrouter_model_secondary,
        "llm_concurrency": settings.llm_concurrency,
        "auto_accept_threshold": settings.auto_accept_threshold,
        "port": settings.port,
        "input_dir": settings.input_dir,
        "output_dir": settings.output_dir,
    }
    SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def reload_settings() -> None:
    """Re-read env vars and overlay file settings. Updates singleton in-place."""
    fresh = Settings()
    for field in fresh.model_fields:
        setattr(settings, field, getattr(fresh, field))
    _overlay_from_file()


def get_settings_for_api() -> dict:
    """Return settings dict with masked API key for frontend display."""
    return {
        "openrouter_api_key": "****" if settings.openrouter_api_key else "",
        "openrouter_model_primary": settings.openrouter_model_primary,
        "openrouter_model_secondary": settings.openrouter_model_secondary,
        "llm_concurrency": settings.llm_concurrency,
        "auto_accept_threshold": settings.auto_accept_threshold,
        "port": settings.port,
        "input_dir": settings.input_dir,
        "output_dir": settings.output_dir,
    }


# Apply overlay on import
_overlay_from_file()
