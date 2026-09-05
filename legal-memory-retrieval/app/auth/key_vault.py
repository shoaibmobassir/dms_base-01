"""
Key Vault: Secure AES-256-GCM Encryption for Tenant API Keys.
Clean-room independent implementation.
"""

import base64
import os
import secrets
from typing import Dict, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class KeyVault:
    """Handles encryption, decryption, and lifecycle of tenant API keys."""

    def __init__(self, master_secret: Optional[str] = None):
        secret = master_secret or os.environ.get(
            "USER_API_KEYS_ENCRYPTION_SECRET",
            "firmos-dev-master-encryption-secret-32b-minimum-secure",
        )
        # Derive 256-bit AES key using PBKDF2
        salt = b"firmos_key_vault_salt_v1"
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100_000,
        )
        self._key = kdf.derive(secret.encode("utf-8"))
        self._aesgcm = AESGCM(self._key)

    def encrypt_key(self, raw_key: str) -> str:
        """Encrypts a plaintext key string to a base64-encoded ciphertext with nonce."""
        if not raw_key:
            return ""
        nonce = secrets.token_bytes(12)  # 96-bit nonce for AES-GCM
        ciphertext = self._aesgcm.encrypt(nonce, raw_key.encode("utf-8"), None)
        # Combined nonce + ciphertext
        payload = nonce + ciphertext
        return base64.urlsafe_b64encode(payload).decode("utf-8")

    def decrypt_key(self, encrypted_payload: str) -> str:
        """Decrypts a base64-encoded payload back to plaintext key."""
        if not encrypted_payload:
            return ""
        try:
            payload = base64.urlsafe_b64decode(encrypted_payload.encode("utf-8"))
            nonce = payload[:12]
            ciphertext = payload[12:]
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode("utf-8")
        except Exception as exc:
            raise ValueError(f"Failed to decrypt API key: {exc}") from exc


_vault_instance: Optional[KeyVault] = None


def get_key_vault() -> KeyVault:
    global _vault_instance
    if _vault_instance is None:
        _vault_instance = KeyVault()
    return _vault_instance
