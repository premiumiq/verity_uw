"""Application configuration from environment variables.

Loads settings from:
1. Environment variables (highest priority)
2. .env file in the project root (loaded automatically)

The .env file is NOT committed to git (.gitignore) — it contains
your ANTHROPIC_API_KEY and other secrets.
"""

import os
from pathlib import Path


# Load .env file if it exists.
# Looks for .env in the current working directory (where you run uvicorn from).
# This is the standard convention — no hardcoded paths, works regardless
# of where the code is installed.
_env_file = Path.cwd() / ".env"
if _env_file.exists():
    for line in _env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            # Only set if not already in environment (env vars take priority)
            if key not in os.environ:
                os.environ[key] = value


class Settings:
    VERITY_DB_URL: str = os.getenv(
        "VERITY_DB_URL", "postgresql://verityuser:veritypass123@localhost:5432/verity_db"
    )
    PAS_DB_URL: str = os.getenv(
        "PAS_DB_URL", "postgresql://verityuser:veritypass123@localhost:5432/pas_db"
    )
    MINIO_ENDPOINT: str = os.getenv("MINIO_ENDPOINT", "localhost:9000")
    MINIO_ACCESS_KEY: str = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
    MINIO_SECRET_KEY: str = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
    MINIO_SECURE: bool = os.getenv("MINIO_SECURE", "false").lower() == "true"
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    APP_ENV: str = os.getenv("APP_ENV", "demo")


settings = Settings()
