"""Graph explorer response (api-contracts.md, Phase 8)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

NodeType = Literal["SalesPerson", "Deal", "Client", "Domain"]


class GraphNode(BaseModel):
    id: str  # SP-/DL-/CL- ids are unique by prefix; Domain nodes use their name
    label: str
    type: NodeType
    props: dict[str, Any]


class GraphLink(BaseModel):
    source: str
    target: str
    type: Literal["OWNS", "FOR_CLIENT", "IN_DOMAIN", "EXPERTISE_IN", "SIMILAR_TO"]
    props: dict[str, Any]


class SubgraphOut(BaseModel):
    nodes: list[GraphNode]
    links: list[GraphLink]
