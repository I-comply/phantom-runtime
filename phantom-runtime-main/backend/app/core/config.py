import os
from dotenv import load_dotenv
from pathlib import Path

ROOT_DIR = Path(__file__).parent.parent.parent
load_dotenv(ROOT_DIR / '.env')


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/phantomos"
    )
    # Explicit per-origin list by default; "*" must be opted into deliberately
    # (see main.py, which refuses to combine "*" with credentialed CORS).
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173")
    # One-time bootstrap credential for minting the very first admin API key
    # (POST /api/v3/security/api-keys has no other caller once auth is required).
    # Unset in production once an admin key exists; treat it like any other secret.
    BOOTSTRAP_ADMIN_KEY: str | None = os.getenv("PHANTOM_BOOTSTRAP_ADMIN_KEY")

    # Cross-instance reconciliation daemon (app/core/reconciler.py). Off by default.
    RECONCILER_ENABLED: bool = os.getenv("RECONCILER_ENABLED", "false").lower() in ("1", "true", "yes")
    RECONCILER_NODE_ID: str = os.getenv("RECONCILER_NODE_ID", os.getenv("HOSTNAME", "node-0"))
    RECONCILER_SHARED_SECRET: str | None = os.getenv("RECONCILER_SHARED_SECRET")
    RECONCILER_PEERS: str = os.getenv("RECONCILER_PEERS", "")  # "id=url,id=url"
    RECONCILER_INTERVAL: float = float(os.getenv("RECONCILER_INTERVAL", "5"))


settings = Settings()
