"""Text embeddings for domain similarity (local model, nothing leaves the machine).

The model (config `domains.embedding_model`, default BAAI/bge-small-en-v1.5, ~65 MB) runs
locally with fastembed / ONNX Runtime. It is downloaded once into `api/.models` and loaded
lazily the first time a NEW domain is created; the built-in domains use the vectors stored in
`domain_embeddings.json`, so seeding, recompute and tests never need the model.
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from collections.abc import Sequence
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from app.core.domains import BUILTIN_DOMAINS

logger = logging.getLogger(__name__)

MODEL_CACHE_DIR = Path(__file__).resolve().parents[2] / ".models"  # api/.models (git-ignored)
BUILTIN_EMBEDDINGS_FILE = Path(__file__).with_name("domain_embeddings.json")


class EmbeddingsUnavailable(RuntimeError):
    """The embedding model could not be loaded (e.g. offline on first use)."""


class Embedder(Protocol):
    model_name: str

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Lazy, thread-safe wrapper around fastembed.TextEmbedding."""

    def __init__(self, model_name: str, cache_dir: Path = MODEL_CACHE_DIR) -> None:
        self.model_name = model_name
        self._cache_dir = cache_dir
        self._model: object | None = None
        self._lock = threading.Lock()

    def _load(self) -> object:
        with self._lock:
            if self._model is None:
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                try:
                    from fastembed import TextEmbedding

                    logger.info("Loading embedding model %s (first use)", self.model_name)
                    self._model = TextEmbedding(self.model_name, cache_dir=str(self._cache_dir))
                except Exception as exc:  # download / ONNX runtime problems
                    raise EmbeddingsUnavailable(
                        f"Could not load the embedding model {self.model_name}: {exc}"
                    ) from exc
            return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        return [normalise([float(x) for x in vector]) for vector in model.embed(list(texts))]  # type: ignore[attr-defined]


_override: Embedder | None = None


@lru_cache(maxsize=4)
def _default(model_name: str) -> Embedder:
    return FastEmbedEmbedder(model_name)


def get_embedder(model_name: str) -> Embedder:
    """The process-wide embedder (tests can replace it with `set_embedder`)."""
    return _override if _override is not None else _default(model_name)


def set_embedder(embedder: Embedder | None) -> None:
    global _override
    _override = embedder


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vector))
    return [x / norm for x in vector] if norm else list(vector)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (normalised again here, so any vectors work)."""
    if len(a) != len(b):
        raise ValueError(f"vector sizes differ: {len(a)} vs {len(b)}")
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


@lru_cache(maxsize=1)
def builtin_embeddings() -> dict:
    """{"model": name, "vectors": {domain: [floats]}} for the 5 built-in domains."""
    data = json.loads(BUILTIN_EMBEDDINGS_FILE.read_text(encoding="utf-8"))
    missing = set(BUILTIN_DOMAINS) - set(data["vectors"])
    if missing:
        raise RuntimeError(f"{BUILTIN_EMBEDDINGS_FILE.name} is missing: {sorted(missing)}")
    return data
