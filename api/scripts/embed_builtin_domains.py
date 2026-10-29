"""Regenerate app/core/domain_embeddings.json (embeddings of the 5 built-in domains).

Run after changing BUILTIN_DESCRIPTIONS in app/core/domains.py or the embedding model in
config.yaml. Downloads the model into api/.models on first use.

    python scripts/embed_builtin_domains.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.core.config import get_config  # noqa: E402
from app.core.domains import BUILTIN_DESCRIPTIONS, BUILTIN_DOMAINS, embedding_text  # noqa: E402
from app.core.embeddings import BUILTIN_EMBEDDINGS_FILE, FastEmbedEmbedder  # noqa: E402


def main() -> None:
    model = get_config().domains.embedding_model
    embedder = FastEmbedEmbedder(model)
    texts = [embedding_text(d, BUILTIN_DESCRIPTIONS[d]) for d in BUILTIN_DOMAINS]
    vectors = embedder.embed(texts)
    data = {
        "model": model,
        "vectors": {
            d: [round(x, 6) for x in v] for d, v in zip(BUILTIN_DOMAINS, vectors, strict=True)
        },
    }
    BUILTIN_EMBEDDINGS_FILE.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    print(
        f"Wrote {BUILTIN_EMBEDDINGS_FILE} ({len(vectors)} domains, {len(vectors[0])} dims, {model})"
    )


if __name__ == "__main__":
    main()
