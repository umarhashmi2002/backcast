"""Embedding providers.

``BedrockEmbedder`` calls Amazon Titan Text Embeddings v2 (L2-normalized, 1024
dims by default). ``HashEmbedder`` is a dependency-free, deterministic fallback
for offline development and CI — it uses the hashing trick so shared tokens
produce correlated vectors, but it is NOT semantically meaningful. Select the
provider by setting ``BACKCAST_EMBEDDING_MODEL_ID`` (use ``hash`` for offline).
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from ..config import Settings, get_settings
from ..telemetry import get_logger

if TYPE_CHECKING:
    from mypy_boto3_bedrock_runtime import BedrockRuntimeClient

log = get_logger(__name__)

_OFFLINE_SENTINELS = {"hash", "fake", "local", "offline"}


@runtime_checkable
class Embedder(Protocol):
    dimensions: int

    def embed_one(self, text: str) -> list[float]: ...

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class HashEmbedder:
    """Deterministic, L2-normalized pseudo-embeddings for offline use."""

    def __init__(self, dimensions: int = 1024) -> None:
        self.dimensions = dimensions

    def embed_one(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        for token in text.lower().split():
            digest = hashlib.sha1(token.encode("utf-8")).digest()
            idx = int.from_bytes(digest[:4], "big") % self.dimensions
            vec[idx] += 1.0 if digest[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_one(t) for t in texts]


class BedrockEmbedder:
    """Amazon Titan Text Embeddings v2 via Bedrock."""

    def __init__(self, model_id: str, region: str, dimensions: int = 1024) -> None:
        import boto3

        self.model_id = model_id
        self.dimensions = dimensions
        self._client: BedrockRuntimeClient = boto3.client("bedrock-runtime", region_name=region)

    def embed_one(self, text: str) -> list[float]:
        body = json.dumps({"inputText": text, "dimensions": self.dimensions, "normalize": True})
        response = self._client.invoke_model(
            modelId=self.model_id,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read())
        embedding: list[float] = payload["embedding"]
        return embedding

    def embed(self, texts: list[str]) -> list[list[float]]:
        # Titan embeds a single input per call; loop (batches are discouraged).
        return [self.embed_one(t) for t in texts]


def build_embedder(settings: Settings | None = None) -> Embedder:
    """Construct the configured embedder (Bedrock, or offline hash fallback)."""
    cfg = settings or get_settings()
    if cfg.embedding_model_id.lower() in _OFFLINE_SENTINELS:
        log.info("embedder.offline", dimensions=cfg.embedding_dims)
        return HashEmbedder(cfg.embedding_dims)
    return BedrockEmbedder(cfg.embedding_model_id, cfg.aws_region, cfg.embedding_dims)
