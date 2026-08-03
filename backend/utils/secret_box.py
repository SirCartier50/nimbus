"""Symmetric encryption for user-supplied secrets at rest (their own LLM provider
API keys — see UserSettings.provider_keys_enc). Distinct from aws_role_arn/
aws_external_id on the same table, which are deliberately left unencrypted
(neither is a secret; see the comment on UserSettings). A pasted-in HuggingFace/
Groq/OpenRouter key IS a secret, so it doesn't get the same pass.

Fernet (symmetric, authenticated) rather than one-way hashing: we need the
plaintext back to call the provider's API on the user's behalf, not just to
compare it later.
"""
import functools
import os

from cryptography.fernet import Fernet, InvalidToken


class SecretBoxNotConfigured(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = os.getenv("SETTINGS_ENCRYPTION_KEY")
    if not key:
        # Fail closed: better to refuse the feature than to silently store
        # plaintext keys, or crash the whole process for users who never touch it.
        raise SecretBoxNotConfigured(
            "SETTINGS_ENCRYPTION_KEY is not set — cannot store or read user API keys. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode())


def encrypt_secret(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        # Ciphertext from a different/rotated SETTINGS_ENCRYPTION_KEY. Treat it
        # like "not set" rather than crashing the turn — the operator-key
        # fallback in get_provider() still covers the user.
        raise SecretBoxNotConfigured("Stored key can't be decrypted with the current SETTINGS_ENCRYPTION_KEY")


