
"""Encryption helpers for private MailFlow Studio credentials."""

import os

from cryptography.fernet import Fernet, InvalidToken


def get_fernet() -> Fernet:
    """Load the encryption key from the environment."""
    key = os.environ.get("MAIL_SETTINGS_ENCRYPTION_KEY", "").strip()

    if not key:
        raise RuntimeError(
            "MAIL_SETTINGS_ENCRYPTION_KEY is not configured."
        )

    try:
        return Fernet(key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        raise RuntimeError(
            "MAIL_SETTINGS_ENCRYPTION_KEY is invalid."
        ) from None


def encrypt_secret(secret: str) -> str:
    """Encrypt a secret before storing it in the database."""
    if not secret:
        raise ValueError("The secret cannot be empty.")

    return get_fernet().encrypt(secret.encode("utf-8")).decode("ascii")


def decrypt_secret(encrypted_secret: str) -> str:
    """Decrypt a previously encrypted secret when it is needed."""
    if not encrypted_secret:
        raise ValueError("No encrypted secret was provided.")

    try:
        return get_fernet().decrypt(
            encrypted_secret.encode("ascii")
        ).decode("utf-8")
    except (InvalidToken, ValueError, UnicodeEncodeError):
        raise RuntimeError(
            "The saved credential could not be decrypted. "
            "Check the encryption key configuration."
        ) from None
