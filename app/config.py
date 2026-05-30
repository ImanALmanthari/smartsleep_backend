# ─────────────────────────────────────────────────────────────────────────────
# config.py  –  Application configuration loaded from environment variables.
#
# We NEVER hard-code secrets (passwords, API keys, tokens) directly in source
# code because anyone who sees the code would also see the secret.
# Instead we store secrets in a ".env" file (never committed to git) and
# read them here using Pydantic's BaseSettings class.
# ─────────────────────────────────────────────────────────────────────────────

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Central configuration class — reads every field from environment variables.

    Pydantic automatically reads these values from:
    1. A .env file in the project root (for local development)
    2. Real environment variables (for deployment on Render, Heroku, etc.)

    If a required field (no default value) is missing, the app will crash
    on startup with a clear error message — this is intentional and helps
    you catch misconfiguration early.
    """

    # ── General ───────────────────────────────────────────────────────────────
    app_env: str = "development"  # "development" or "production"

    # ── JWT (JSON Web Token) settings ─────────────────────────────────────────
    # JWT is how we prove a user is logged in without checking the database
    # on every request. After login, the server issues a signed "token" string.
    # The client sends this token with every subsequent request.
    secret_key: str              # Long random string used to sign/verify JWTs — KEEP SECRET
    algorithm: str = "HS256"     # HMAC-SHA256 signing algorithm
    access_token_expire_minutes: int = 60  # Tokens are valid for 1 hour

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: Optional[str] = None  # PostgreSQL URL (optional; we use Supabase client instead)

    # ── Supabase (our cloud database + auth provider) ─────────────────────────
    supabase_url: str             # The URL of your Supabase project
    supabase_service_key: str     # Service-role key: bypasses Row Level Security (admin access)
    supabase_anon_key: str        # Anon key: respects Row Level Security (public access)

    # ── Cloudflare R2 (S3-compatible object storage for ML model files) ───────
    r2_access_key_id: Optional[str] = None      # R2 API key ID
    r2_secret_access_key: Optional[str] = None  # R2 API secret
    r2_endpoint_url: Optional[str] = None       # R2 bucket endpoint URL
    r2_bucket_name: Optional[str] = None        # Name of the R2 bucket

    # ── Email relay (Google Apps Script webhook) ──────────────────────────────
    # Instead of setting up an SMTP server, we relay emails through a
    # Google Apps Script (GAS) URL. The script runs in Google's cloud
    # and sends emails via Gmail.
    google_script_url: str = ""  # URL of the Google Apps Script web app
    email_token: str = ""        # Secret token the script checks to prevent spam
    email_name: str = "Smart Sleep Service"  # The "From" display name in emails
    frontend_url: str = "https://smartsleep-api.onrender.com"  # Used in confirmation links

    # ── Tell Pydantic where to find the .env file ─────────────────────────────
    model_config = SettingsConfigDict(env_file=".env")


# Create one global instance that the whole app imports.
# Pydantic reads the .env file exactly once at startup.
settings = Settings()
