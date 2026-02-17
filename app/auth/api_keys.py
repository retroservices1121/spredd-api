import hashlib
import secrets


def generate_api_key() -> tuple[str, str, str]:
    """Generate an API key. Returns (full_key, prefix, key_hash)."""
    random_part = secrets.token_hex(32)
    full_key = f"sprdd_pk_{random_part}"
    prefix = full_key[:16]
    key_hash = hashlib.sha256(full_key.encode()).hexdigest()
    return full_key, prefix, key_hash


def hash_api_key(key: str) -> str:
    """Hash an API key with SHA-256."""
    return hashlib.sha256(key.encode()).hexdigest()


def validate_key_format(key: str) -> bool:
    """Check if a key has the expected format."""
    return key.startswith("sprdd_pk_") and len(key) == 73
