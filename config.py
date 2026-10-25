
"""Application configuration for MailFlow Studio."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load private settings from the project's .env file.
load_dotenv(BASE_DIR / ".env")

INSTANCE_DIR = BASE_DIR / "instance"
DATABASE_PATH = INSTANCE_DIR / "mailflow.db"


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY")

    if not SECRET_KEY:
        raise RuntimeError(
            "FLASK_SECRET_KEY is missing. "
            "Add a strong random secret to your .env file."
        )
    if len(SECRET_KEY) < 32:
        raise RuntimeError(
            "FLASK_SECRET_KEY must contain at least 32 characters. "
            "Generate a new random secret and update your .env file."
        )

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        f"sqlite:///{DATABASE_PATH.as_posix()}",
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = 15 * 1024 * 1024

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
    SESSION_PROTECTION = "strong"
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SECURE = os.environ.get("COOKIE_SECURE", "1") == "1"
    REMEMBER_COOKIE_SAMESITE = "Lax"
