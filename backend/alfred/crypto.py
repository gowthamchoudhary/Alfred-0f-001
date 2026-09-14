"""Credential-at-rest encryption for Alfred (Fernet, ALFRED_ENCRYPTION_KEY).

Why this exists
---------------
Alfred's original credential model was strictly per-request: a GitHub token
existed in memory for the duration of one investigation and vanished. That is
still the model for manual/API-triggered runs. But automatic background
triggering (poller → triage → auto-invoke) fires unattended — no human is
present to supply a token at that moment. To let an unattended run still post
its verdict issue, the user provides their GitHub token ONCE at watchlist
registration; it is stored ENCRYPTED AT REST on that watchlist entry, tied to
exactly one dependency.

Threat model / rules
--------------------
* Key comes from the ALFRED_ENCRYPTION_KEY env var (Fernet key, url-safe
  base64-encoded 32 bytes) — never from the database, never hard-coded.
* Only ciphertext is stored. The DB never sees plaintext tokens.
* Plaintext exists in memory only for the duration of a single run
  (decrypt → use → discard); it is never logged, never returned by any API,
  and never written to any other table.
* Missing/unset key or a failed decrypt → log honestly and continue with
  reduced capability (the ACTION step skips cleanly). Never crash the pipeline.
* generate_key() exists so operators can mint a key:
  ``python -c "from alfred.crypto import generate_key; print(generate_key())"``
"""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken

ENV_VAR = "ALFRED_ENCRYPTION_KEY"


class EncryptionKeyMissing(RuntimeError):
    """ALFRED_ENCRYPTION_KEY is not configured — cannot encrypt/decrypt."""


def generate_key() -> str:
    """Mint a fresh Fernet key for ALFRED_ENCRYPTION_KEY (operator helper)."""
    return Fernet.generate_key().decode("ascii")


def _fernet() -> Fernet:
    raw = os.environ.get(ENV_VAR, "").strip()
    if not raw:
        raise EncryptionKeyMissing(
            f"{ENV_VAR} is not set — encrypted watchlist credentials are disabled. "
            "Generate one with: python -c \"from alfred.crypto import generate_key; print(generate_key())\""
        )
    # Tolerate keys with or without surrounding quotes; validate cheaply.
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise EncryptionKeyMissing(
            f"{ENV_VAR} is set but is not a valid Fernet key. "
            "Generate one with: python -c \"from alfred.crypto import generate_key; print(generate_key())\""
        ) from exc


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret at rest. Raises EncryptionKeyMissing when unconfigured."""
    if not plaintext:
        raise ValueError("cannot encrypt an empty secret")
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt an at-rest secret. Raises EncryptionKeyMissing on a bad key."""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionKeyMissing(
            f"{ENV_VAR} does not match the key that encrypted this credential "
            "(key rotation or wrong environment)."
        ) from exc


def mask_secret(plaintext: str) -> str:
    """Display-safe fingerprint, e.g. ``ghp_…3f9a`` — safe for API responses."""
    if not plaintext:
        return ""
    tail = plaintext[-4:] if len(plaintext) >= 8 else "*" * len(plaintext)
    return f"…{tail}"
