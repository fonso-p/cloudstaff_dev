"""API keys and other secrets: environment variables first, then the repo's .env file (git-ignored; see .env.example).

Keys in use: COMPANIES_HOUSE_API_KEY (officers), ADZUNA_APP_ID / ADZUNA_APP_KEY (Adzuna jobs check).
"""
import os

from .paths import REPO

ENV_FILE = REPO / ".env"


def read_env(path=ENV_FILE) -> dict:
    """KEY=VALUE lines from a .env file (quotes stripped, # comments ignored). Missing file -> {}."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip().removeprefix("export ").strip()] = v.strip().strip("'\"")
    return out


def get(key: str, default: str = "", path=ENV_FILE) -> str:
    """One secret: the environment variable if set, else the .env value, else default."""
    return os.environ.get(key) or read_env(path).get(key, default)
