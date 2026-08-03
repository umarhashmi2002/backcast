"""Externally-signed ledger checkpoints — integrity beyond a database admin.

The ``event_ledger`` is tamper-evident *within* the database (a hash chain). To make
it tamper-evident beyond someone who could rewrite the whole chain, we periodically
sign the chain's current **root hash** (the latest ``entry_hash``) with an external
signer and store the signed checkpoint. Forging history then requires rewriting the
chain AND forging the signature.

Signers:
* ``KmsSigner`` — AWS KMS asymmetric key (real, used in Lambda).
* ``LocalHmacSigner`` — HMAC-SHA256 for offline dev/CI (verifiable without AWS).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from ..config import Settings, get_settings
from ..telemetry import get_logger

if TYPE_CHECKING:
    from .engine import MemoryEngine

log = get_logger(__name__)


@dataclass
class Checkpoint:
    incident_id: UUID
    seq_covered: int
    root_hash: str
    signature: str  # base64
    key_id: str
    algorithm: str


class Signer(Protocol):
    key_id: str
    algorithm: str

    def sign(self, message: bytes) -> bytes: ...

    def verify(self, message: bytes, signature: bytes) -> bool: ...


class LocalHmacSigner:
    """HMAC-SHA256 signer for offline use (symmetric; not a KMS asymmetric key)."""

    algorithm = "HMAC_SHA_256"

    def __init__(self, key: bytes | None = None, key_id: str = "local-hmac") -> None:
        self._key = key or os.environ.get("BACKCAST_CHECKPOINT_KEY", "backcast-dev").encode()
        self.key_id = key_id

    def sign(self, message: bytes) -> bytes:
        return hmac.new(self._key, message, hashlib.sha256).digest()

    def verify(self, message: bytes, signature: bytes) -> bool:
        return hmac.compare_digest(self.sign(message), signature)


class KmsSigner:
    """AWS KMS asymmetric signer (default ECDSA over SHA-256)."""

    def __init__(self, key_id: str, region: str, algorithm: str = "ECDSA_SHA_256") -> None:
        import boto3

        self.key_id = key_id
        self.algorithm = algorithm
        self._kms: Any = boto3.client("kms", region_name=region)

    def sign(self, message: bytes) -> bytes:
        resp = self._kms.sign(
            KeyId=self.key_id, Message=message, MessageType="RAW", SigningAlgorithm=self.algorithm
        )
        signature: bytes = resp["Signature"]
        return signature

    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            resp = self._kms.verify(
                KeyId=self.key_id, Message=message, MessageType="RAW",
                Signature=signature, SigningAlgorithm=self.algorithm,
            )
            return bool(resp["SignatureValid"])
        except Exception as exc:  # verification failure or transient error
            log.warning("checkpoint.verify_error", error=str(exc).splitlines()[0])
            return False


def build_signer(settings: Settings | None = None) -> Signer:
    """KMS signer if ``BACKCAST_CHECKPOINT_KEY_ID`` is set, else the offline HMAC signer."""
    cfg = settings or get_settings()
    key_id = os.environ.get("BACKCAST_CHECKPOINT_KEY_ID")
    if key_id:
        return KmsSigner(key_id, cfg.aws_region)
    return LocalHmacSigner()


class LedgerCheckpointer:
    def __init__(self, engine: MemoryEngine, signer: Signer | None = None) -> None:
        self._engine = engine
        self._signer = signer or build_signer(engine.settings)

    def _head(self, incident_id: UUID | str) -> tuple[int, str]:
        row = self._engine.conn.execute(
            "SELECT seq, entry_hash FROM event_ledger WHERE incident_id = %s ORDER BY seq DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        return (int(row["seq"]), str(row["entry_hash"])) if row else (0, "")

    def checkpoint(self, org_id: str, incident_id: UUID | str) -> Checkpoint:
        """Sign the current ledger root hash and persist a checkpoint."""
        seq, root = self._head(incident_id)
        if not root:
            raise ValueError(f"no ledger entries to checkpoint for incident {incident_id}")
        signature = base64.b64encode(self._signer.sign(root.encode())).decode()
        self._engine.conn.execute(
            "INSERT INTO ledger_checkpoints "
            "(org_id, incident_id, seq_covered, root_hash, signature, key_id, algorithm) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (org_id, incident_id, seq, root, signature, self._signer.key_id, self._signer.algorithm),
        )
        log.info("checkpoint.created", incident_id=str(incident_id), seq=seq, key_id=self._signer.key_id)
        return Checkpoint(
            incident_id=UUID(str(incident_id)), seq_covered=seq, root_hash=root,
            signature=signature, key_id=self._signer.key_id, algorithm=self._signer.algorithm,
        )

    def verify_latest(self, incident_id: UUID | str) -> bool:
        """Verify the hash chain AND the latest checkpoint's signature + coverage."""
        if not self._engine.ledger.verify(incident_id):
            return False
        cp = self._engine.conn.execute(
            "SELECT seq_covered, root_hash, signature FROM ledger_checkpoints "
            "WHERE incident_id = %s ORDER BY seq_covered DESC LIMIT 1",
            (incident_id,),
        ).fetchone()
        if cp is None:
            return True  # chain verified; nothing checkpointed yet
        if not self._signer.verify(str(cp["root_hash"]).encode(), base64.b64decode(cp["signature"])):
            return False
        entry = self._engine.conn.execute(
            "SELECT entry_hash FROM event_ledger WHERE incident_id = %s AND seq = %s",
            (incident_id, cp["seq_covered"]),
        ).fetchone()
        return entry is not None and str(entry["entry_hash"]) == str(cp["root_hash"])
