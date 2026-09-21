"""Encrypt / decrypt OAuth tokens for source_connections."""
from __future__ import annotations

from app.auth.key_vault import KeyVault
from app.config import settings

_vault: KeyVault | None = None


def _get_vault() -> KeyVault:
    global _vault
    if _vault is None:
        _vault = KeyVault(master_secret=settings.sources_token_encryption_secret)
    return _vault


def encrypt_token(raw: str) -> str:
    if not raw:
        return ""
    return _get_vault().encrypt_key(raw)


def decrypt_token(payload: str) -> str:
    if not payload:
        return ""
    return _get_vault().decrypt_key(payload)


def reset_crypto_for_tests() -> None:
    global _vault
    _vault = None
