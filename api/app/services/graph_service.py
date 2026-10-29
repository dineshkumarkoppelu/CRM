"""Builds the graph-explorer subgraph around one sales person (Phase 8)."""

from __future__ import annotations

from typing import Any

from app.core.errors import AppError
from app.models.graph import GraphLink, GraphNode, SubgraphOut
from app.repositories import graph_repo


class _Builder:
    """Collects nodes (deduplicated by id) and links."""

    def __init__(self) -> None:
        self.nodes: dict[str, GraphNode] = {}
        self.links: list[GraphLink] = []

    def node(self, node_id: str, label: str, node_type: str, props: dict[str, Any]) -> None:
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(id=node_id, label=label, type=node_type, props=props)

    def link(self, source: str, target: str, link_type: str, props: dict[str, Any]) -> None:
        self.links.append(GraphLink(source=source, target=target, type=link_type, props=props))

    def build(self) -> SubgraphOut:
        return SubgraphOut(nodes=list(self.nodes.values()), links=self.links)


async def get_subgraph(
    rep_id: str, include_peers: bool = True, deal_status: str | None = None
) -> SubgraphOut:
    rep = await graph_repo.get_rep(rep_id)
    if rep is None:
        raise AppError("REP_NOT_FOUND", f"Sales person {rep_id} not found", 404, {"id": rep_id})

    g = _Builder()
    g.node(rep["id"], rep["name"], "SalesPerson", {k: v for k, v in rep.items() if k != "name"})

    for d in await graph_repo.rep_deals(rep_id, deal_status):
        g.node(
            d["deal_id"],
            d["title"],
            "Deal",
            {
                k: d[k]
                for k in (
                    "status",
                    "stage",
                    "value",
                    "created_at",
                    "closed_at",
                    "expected_close_date",
                    "domain",
                )
            },  # fmt: skip
        )
        g.node(
            d["client_id"],
            d["client_name"],
            "Client",
            {"industry": d["industry"], "size": d["size"]},
        )
        g.node(d["domain"], d["domain"], "Domain", {})
        g.link(rep_id, d["deal_id"], "OWNS", {})
        g.link(d["deal_id"], d["client_id"], "FOR_CLIENT", {})
        g.link(d["deal_id"], d["domain"], "IN_DOMAIN", {})

    for e in await graph_repo.rep_expertise(rep_id):
        g.node(e["domain"], e["domain"], "Domain", {})
        g.link(rep_id, e["domain"], "EXPERTISE_IN", {k: v for k, v in e.items() if k != "domain"})

    if include_peers:
        for p in await graph_repo.rep_peers(rep_id):
            g.node(
                p["id"],
                p["name"],
                "SalesPerson",
                {"region": p["region"], "active": p["active"], "capacity": p["capacity"],
                 "peer": True},
            )  # fmt: skip
            g.link(
                p["source"],
                p["target"],
                "SIMILAR_TO",
                {"score": p["score"], "matched_domains": p["matched_domains"],
                 "match_count": p["match_count"]},
            )  # fmt: skip
    return g.build()
