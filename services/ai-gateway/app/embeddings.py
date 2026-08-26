"""Text embeddings behind a stable contract, same mock-first precedent as
media.py's STT/TTS providers: a deterministic mock keeps RAG retrieval
provable in CI without any model weights, and the real backend (a small
local sentence-transformer per docs/MODEL_CARD.md) is deferred to GPU
deployment without changing this interface.
"""

import hashlib
import math
from abc import ABC, abstractmethod

from pydantic import BaseModel, Field

MOCK_EMBEDDER_MODEL = "aiva-mock-deterministic-embed"
SENTENCE_TRANSFORMER_MODEL_DEFAULT = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384
MAX_EMBED_CHARS = 8000


class Embedding(BaseModel):
    vector: list[float] = Field(min_length=EMBEDDING_DIM, max_length=EMBEDDING_DIM)
    dim: int = Field(ge=1)
    provider: str
    model_id: str


class EmbeddingProvider(ABC):
    @property
    @abstractmethod
    def model_id(self) -> str: ...

    @abstractmethod
    async def embed(self, text: str) -> Embedding: ...


class MockEmbedder(EmbeddingProvider):
    """Deterministic stand-in for a real sentence-transformer.

    The vector is a hash-seeded, L2-normalized pseudo-embedding derived only
    from the input text, so repeated calls with the same text produce
    byte-identical vectors (needed for the mock golden-set style determinism
    guarantee) while making clear this is not semantic similarity from a
    trained model — it is schema/shape-compatible, not meaning-compatible.
    """

    @property
    def model_id(self) -> str:
        return MOCK_EMBEDDER_MODEL

    async def embed(self, text: str) -> Embedding:
        values: list[float] = []
        block = hashlib.sha256(text.encode("utf-8")).digest()
        while len(values) < EMBEDDING_DIM:
            block = hashlib.sha256(block).digest()
            values.extend((byte - 127.5) / 127.5 for byte in block)
        vector = values[:EMBEDDING_DIM]
        norm = math.sqrt(sum(component * component for component in vector)) or 1.0
        normalized = [component / norm for component in vector]
        return Embedding(
            vector=normalized, dim=EMBEDDING_DIM, provider="mock", model_id=self.model_id
        )


class SentenceTransformerEmbedder(EmbeddingProvider):
    """Real embedding path; requires the sentence-transformers package and weights."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        try:
            import sentence_transformers  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; pull model weights at "
                "deployment per docs/MODEL_CARD.md before selecting this backend"
            ) from exc

    @property
    def model_id(self) -> str:
        return self.model_name

    async def embed(self, text: str) -> Embedding:
        del text
        raise RuntimeError("sentence-transformers inference lands with GPU deployment")


def build_embedder(backend: str, model_name: str) -> EmbeddingProvider:
    if backend == "mock":
        return MockEmbedder()
    if backend == "sentence-transformers":
        return SentenceTransformerEmbedder(model_name)
    raise ValueError(f"Unknown embedding backend: {backend}")


__all__ = [
    "EMBEDDING_DIM",
    "MAX_EMBED_CHARS",
    "Embedding",
    "EmbeddingProvider",
    "MockEmbedder",
    "SentenceTransformerEmbedder",
    "build_embedder",
]
