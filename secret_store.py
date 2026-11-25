"""Authenticated encryption helpers for persisted user credentials."""

from __future__ import annotations

from cryptography.fernet import Fernet

from config import Config

_PREFIX = "fernet:v1:"


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(_PREFIX)


def _cipher() -> Fernet:
    key = Config.CREDENTIAL_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "CREDENTIAL_ENCRYPTION_KEY is required to store or decrypt credentials"
        )
    try:
        return Fernet(key.encode("ascii"))
    except (UnicodeEncodeError, ValueError) as error:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is invalid") from error


def encrypt_secret(value: str | None) -> str | None:
    if value is None or is_encrypted(value):
        return value
    if not isinstance(value, str):
        raise TypeError("Credential values must be strings")
    token = _cipher().encrypt(value.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt_secret(value: str | None) -> str | None:
    if value is None or not is_encrypted(value):
        return value
    token = value[len(_PREFIX) :].encode("ascii")
    return _cipher().decrypt(token).decode("utf-8")
