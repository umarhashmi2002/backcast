"""Webhook authentication — HMAC signature + replay protection.

A public ingress must not trust its callers. Alert sources sign each webhook with a
shared secret over ``"<timestamp>." + body``; Backcast recomputes the HMAC and
rejects anything that doesn't match, is missing headers, or is too old (replay).
"""

from __future__ import annotations

import hashlib
import hmac
import time

SIGNATURE_HEADER = "x-backcast-signature"
TIMESTAMP_HEADER = "x-backcast-timestamp"


def sign_payload(secret: str, body: bytes, timestamp: int) -> str:
    """Compute the expected signature for a body at a timestamp (also used by clients/tests)."""
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"


def verify_webhook(
    *,
    secret: str,
    body: bytes,
    signature: str | None,
    timestamp: str | None,
    max_age_seconds: int = 300,
    now: float | None = None,
) -> bool:
    """Return True iff the signature is valid and the timestamp is fresh."""
    if not signature or not timestamp:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs((now if now is not None else time.time()) - ts) > max_age_seconds:
        return False  # replay / clock-skew protection
    expected = sign_payload(secret, body, ts)
    return hmac.compare_digest(expected, signature)
