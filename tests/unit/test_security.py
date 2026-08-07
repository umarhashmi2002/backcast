"""Unit tests for webhook HMAC verification (no AWS/DB)."""

from __future__ import annotations

from backcast.api.security import sign_payload, verify_webhook

SECRET = "shared-webhook-secret"
BODY = b'{"org_id":"demo","fingerprint":"am-1"}'


def test_valid_signature_accepted() -> None:
    sig = sign_payload(SECRET, BODY, 1000)
    assert (
        verify_webhook(secret=SECRET, body=BODY, signature=sig, timestamp="1000", now=1010) is True
    )


def test_tampered_body_rejected() -> None:
    sig = sign_payload(SECRET, BODY, 1000)
    assert (
        verify_webhook(secret=SECRET, body=b"tampered", signature=sig, timestamp="1000", now=1010)
        is False
    )


def test_wrong_secret_rejected() -> None:
    sig = sign_payload("other-secret", BODY, 1000)
    assert (
        verify_webhook(secret=SECRET, body=BODY, signature=sig, timestamp="1000", now=1010) is False
    )


def test_stale_timestamp_rejected() -> None:
    sig = sign_payload(SECRET, BODY, 1000)
    assert (
        verify_webhook(secret=SECRET, body=BODY, signature=sig, timestamp="1000", now=1400) is False
    )


def test_missing_headers_rejected() -> None:
    assert verify_webhook(secret=SECRET, body=BODY, signature=None, timestamp="1000") is False
    assert verify_webhook(secret=SECRET, body=BODY, signature="sha256=x", timestamp=None) is False
