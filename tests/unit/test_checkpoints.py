"""Unit tests for the checkpoint signer (no AWS/DB)."""

from __future__ import annotations

from backcast.memory.checkpoints import LocalHmacSigner


def test_hmac_signer_roundtrip() -> None:
    signer = LocalHmacSigner(key=b"secret")
    signature = signer.sign(b"root-hash-abc")
    assert signer.verify(b"root-hash-abc", signature) is True
    assert signer.verify(b"tampered", signature) is False


def test_hmac_signer_key_isolation() -> None:
    a = LocalHmacSigner(key=b"key-a")
    b = LocalHmacSigner(key=b"key-b")
    assert b.verify(b"message", a.sign(b"message")) is False
