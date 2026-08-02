"""Lambda runtime helpers: warm-reused engine, Secrets Manager, S3 artifacts."""

from __future__ import annotations

import json
import os
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import get_settings
from ..db.connection import connect
from ..memory import MemoryEngine
from ..telemetry import get_logger

log = get_logger(__name__)

_engine: MemoryEngine | None = None


@lru_cache(maxsize=1)
def get_database_url() -> str:
    """Resolve the CockroachDB DSN, from Secrets Manager if configured, else env."""
    secret_id = os.environ.get("BACKCAST_DATABASE_SECRET")
    if not secret_id:
        return get_settings().database_url

    import boto3

    client = boto3.client("secretsmanager", region_name=get_settings().aws_region)
    raw = client.get_secret_value(SecretId=secret_id).get("SecretString") or ""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(data, dict):
        return raw

    url = data.get("url") or data.get("BACKCAST_DATABASE_URL") or raw
    if not isinstance(url, str):
        return raw

    # If the secret carries the cluster CA cert, materialize it so libpq can do
    # sslmode=verify-full without baking a cluster-specific cert into the image.
    ca_cert = data.get("ca_cert")
    if isinstance(ca_cert, str) and ca_cert.strip():
        cert_path = "/tmp/backcast-root.crt"
        Path(cert_path).write_text(ca_cert)
        if "sslrootcert=" not in url:
            url += ("&" if "?" in url else "?") + f"sslrootcert={cert_path}"
    return url


def get_engine() -> MemoryEngine:
    """Return a warm-reused MemoryEngine, reconnecting if the connection died."""
    global _engine
    if _engine is None or _engine.conn.closed:
        _engine = MemoryEngine(conn=connect(get_database_url()))
    return _engine


def put_artifact(org_id: str, incident_id: str, payload: dict[str, Any]) -> str | None:
    """Store a raw alert payload in S3 if an artifact bucket is configured."""
    bucket = get_settings().artifact_bucket
    if not bucket:
        return None

    import boto3

    key = f"incidents/{org_id}/{incident_id}/alert-{int(time.time() * 1000)}.json"
    boto3.client("s3", region_name=get_settings().aws_region).put_object(
        Bucket=bucket,
        Key=key,
        Body=json.dumps(payload, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return f"s3://{bucket}/{key}"
