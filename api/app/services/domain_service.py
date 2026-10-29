"""Domains: the dynamic domain list, adding a domain, and embedding-based domain similarity.

How a new domain gets its similarity (and therefore a RELATED fit for reps):
1. Its "name: description" text is embedded with a local sentence-embedding model.
2. Cosine similarity to every other domain is stored on RELATED_TO edges (one per pair).
3. For ranking, the top `related_top_k` domains with similarity above `related_min_similarity`
   are used; each counts with weight (similarity - related_min_similarity).
Adding a domain also re-runs the recompute, because the rep-similarity score divides by the
number of domains.

The pure helpers (`related_pairs`, `select_related`) are unit-tested without a database.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from app.core import clock, db
from app.core.config import get_config
from app.core.domains import BUILTIN_DESCRIPTIONS, BUILTIN_DOMAINS, embedding_text
from app.core.embeddings import (
    EmbeddingsUnavailable,
    builtin_embeddings,
    cosine,
    get_embedder,
)
from app.core.errors import AppError
from app.core.numbers import round_half_up
from app.models.domains import DomainCreate, DomainOut, RelatedDomainOut
from app.repositories import domain_repo
from app.services import busy
from app.services.recommendation_service import RelatedDomain

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------
def related_pairs(rows: Iterable[Mapping[str, Any]], model: str) -> list[dict[str, Any]]:
    """Cosine similarity for every pair of domains embedded with `model`, in list order
    (rows ordered built-ins first). One dict per unordered pair: {a, b, similarity}."""
    usable = [r for r in rows if r.get("embedding") and r.get("embedding_model") == model]
    pairs = []
    for i, a in enumerate(usable):
        for b in usable[i + 1 :]:
            similarity = round_half_up(cosine(a["embedding"], b["embedding"]), 4)
            pairs.append({"a": a["name"], "b": b["name"], "similarity": similarity})
    return pairs


def select_related(
    rows: Iterable[Mapping[str, Any]], top_k: int, min_similarity: float
) -> list[RelatedDomain]:
    """The domains a RELATED fit borrows from: top_k by similarity, above the threshold."""
    ordered = sorted(rows, key=lambda r: (-r["similarity"], r["domain"]))
    return [
        RelatedDomain(
            r["domain"], r["similarity"], round_half_up(r["similarity"] - min_similarity, 4)
        )
        for r in ordered
        if r["similarity"] > min_similarity
    ][:top_k]


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
async def domain_names() -> list[str]:
    """All domains in display order: the 5 built-ins, then added domains by creation."""
    return [r["name"] for r in await domain_repo.list_domains()]


async def require_domain(name: str) -> str:
    """Canonical name of an existing domain (case-insensitive); 422 if it does not exist."""
    found = await domain_repo.find_by_name_ci(name)
    if found is None:
        raise AppError(
            "VALIDATION_ERROR",
            f"Unknown domain '{name}'. Add it first (POST /api/domains) or pick an existing one.",
            422,
            {"domain": name},
        )
    return found


async def related_domains(name: str) -> list[RelatedDomain]:
    cfg = get_config().domains
    return select_related(
        await domain_repo.related_for(name), cfg.related_top_k, cfg.related_min_similarity
    )


async def _domain_out(row: Mapping[str, Any]) -> DomainOut:
    cfg = get_config().domains
    rows = await domain_repo.related_for(row["name"])
    used = {r.domain for r in select_related(rows, cfg.related_top_k, cfg.related_min_similarity)}
    return DomainOut(
        name=row["name"],
        description=row["description"],
        builtin=row["builtin"],
        created_at=row["created_at"],
        related=[
            RelatedDomainOut(
                domain=r["domain"], similarity=r["similarity"], used_for_fit=r["domain"] in used
            )
            for r in rows
        ],
    )


async def list_domains() -> list[DomainOut]:
    return [await _domain_out(row) for row in await domain_repo.list_domains()]


# ---------------------------------------------------------------------------
# Writes
# ---------------------------------------------------------------------------
async def ensure_builtin_domains() -> None:
    """Descriptions + stored embeddings on the 5 built-in Domain nodes (idempotent, no model)."""
    data = builtin_embeddings()
    model = get_config().domains.embedding_model
    if data["model"] != model:
        logger.warning(
            "Built-in domain embeddings were made with %s but config uses %s; they will be "
            "re-embedded when a domain is added (run scripts/embed_builtin_domains.py to fix).",
            data["model"],
            model,
        )
    await domain_repo.set_builtins(
        [
            {
                "name": name,
                "description": BUILTIN_DESCRIPTIONS[name],
                "embedding": data["vectors"][name],
                "embedding_model": data["model"],
            }
            for name in BUILTIN_DOMAINS
        ]
    )


async def rebuild_related() -> int:
    """Recompute every RELATED_TO edge from the stored embeddings (no model needed)."""
    model = get_config().domains.embedding_model
    rows = await domain_repo.embeddings()
    skipped = [r["name"] for r in rows if r.get("embedding_model") != model]
    if skipped:
        logger.warning(
            "No %s embedding for domains %s; they get no RELATED_TO edges", model, skipped
        )
    return await domain_repo.rebuild_related(related_pairs(rows, model), clock.today())


async def _embed(texts: Sequence[str], model: str) -> list[list[float]]:
    try:
        return await asyncio.to_thread(get_embedder(model).embed, list(texts))
    except EmbeddingsUnavailable as exc:
        raise AppError(
            "EMBEDDINGS_UNAVAILABLE",
            "The embedding model is not available (it is downloaded once on first use; check "
            "the internet connection and try again)",
            503,
            {"model": model},
        ) from exc


async def create_domain(body: DomainCreate) -> DomainOut:
    """Add a domain: embed it, link it to similar domains, rebuild rep similarity."""
    # Imported here: expertise_service -> domain_service (domain names) would be circular.
    from app.services import expertise_service

    existing = await domain_repo.find_by_name_ci(body.name)
    if existing is not None:
        raise AppError(
            "DOMAIN_EXISTS", f"Domain '{existing}' already exists", 409, {"domain": existing}
        )

    async with busy.exclusive("add domain"):
        with db.no_tx_timeout():
            model = get_config().domains.embedding_model
            # Any domain not yet embedded with the configured model is embedded too.
            stale = [r for r in await domain_repo.embeddings() if r.get("embedding_model") != model]
            texts = [embedding_text(body.name, body.description)]
            texts += [embedding_text(r["name"], r["description"] or r["name"]) for r in stale]
            vectors = await _embed(texts, model)

            await domain_repo.set_embeddings(
                [
                    {"name": r["name"], "embedding": v, "embedding_model": model}
                    for r, v in zip(stale, vectors[1:], strict=True)
                ]
            )
            name = await domain_repo.create(
                name=body.name,
                description=body.description,
                embedding=vectors[0],
                embedding_model=model,
                today=clock.today(),
            )
            await expertise_service.recompute()  # includes RELATED_TO; SIMILAR_TO divisor changed

    logger.info("Added domain %r", name)
    rows = {r["name"]: r for r in await domain_repo.list_domains()}
    return await _domain_out(rows[name])
