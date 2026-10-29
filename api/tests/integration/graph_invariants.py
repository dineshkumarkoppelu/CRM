"""The 8 graph invariants from graph-schema.md as Cypher checks (each returns `violations`).

Used by the seed tests now and by later phases ("graph invariants still hold").
"""

from __future__ import annotations

from datetime import date

from app.core.db import run_read

INVARIANTS: dict[str, str] = {
    "1_deal_has_one_client_and_one_domain": """
        MATCH (d:Deal)
        WHERE COUNT { (d)-[:FOR_CLIENT]->(:Client) } <> 1
           OR COUNT { (d)-[:IN_DOMAIN]->(:Domain) } <> 1
        RETURN count(d) AS violations
    """,
    "2_status_vs_closed_at": """
        MATCH (d:Deal)
        WHERE NOT d.status IN ['OPEN', 'WON', 'LOST']
           OR (d.status = 'OPEN' AND d.closed_at IS NOT NULL)
           OR (d.status IN ['WON', 'LOST']
               AND (d.closed_at IS NULL OR d.closed_at < d.created_at))
        RETURN count(d) AS violations
    """,
    "3_won_reached_negotiation": """
        MATCH (d:Deal {status: 'WON'})
        WHERE d.stage <> 'NEGOTIATION'
           OR d.qualified_at IS NULL OR d.proposal_at IS NULL OR d.negotiation_at IS NULL
        RETURN count(d) AS violations
    """,
    "4_stage_dates_ordered": """
        MATCH (d:Deal)
        WITH d, [x IN [d.created_at, d.qualified_at, d.proposal_at, d.negotiation_at,
                       d.closed_at] WHERE x IS NOT NULL] AS ds
        WHERE any(i IN range(0, size(ds) - 2) WHERE ds[i] > ds[i + 1])
        RETURN count(d) AS violations
    """,
    "5_stage_date_set_iff_reached": """
        MATCH (d:Deal)
        WHERE NOT d.stage IN ['LEAD', 'QUALIFIED', 'PROPOSAL', 'NEGOTIATION']
           OR (d.qualified_at IS NOT NULL) <> (d.stage IN ['QUALIFIED', 'PROPOSAL', 'NEGOTIATION'])
           OR (d.proposal_at IS NOT NULL) <> (d.stage IN ['PROPOSAL', 'NEGOTIATION'])
           OR (d.negotiation_at IS NOT NULL) <> (d.stage = 'NEGOTIATION')
        RETURN count(d) AS violations
    """,
    "6a_activity_has_one_performer_and_one_deal": """
        MATCH (a:Activity)
        WHERE COUNT { (:SalesPerson)-[:PERFORMED]->(a) } <> 1
           OR COUNT { (a)-[:ON_DEAL]->(:Deal) } <> 1
        RETURN count(a) AS violations
    """,
    "6b_activity_date_within_deal_life": """
        MATCH (a:Activity)-[:ON_DEAL]->(d:Deal)
        WHERE a.date < d.created_at OR a.date > coalesce(d.closed_at, $today)
        RETURN count(a) AS violations
    """,
    # Domains are dynamic: the 5 built-ins must exist exactly once; added ones are allowed.
    "7_builtin_domains_present_and_unique": """
        MATCH (d:Domain)
        WITH collect(d.name) AS names
        WITH names, [n IN ['AI', 'Cybersecurity', 'IoT', 'DevOps', 'Cloud Migration']
                     WHERE size([x IN names WHERE x = n]) <> 1] AS bad_builtins
        RETURN size(bad_builtins)
             + size(names) - size(apoc.coll.toSet(names)) AS violations
    """,
    "8_client_created_before_its_deals": """
        MATCH (d:Deal)-[:FOR_CLIENT]->(c:Client)
        WHERE c.created_on > d.created_at
        RETURN count(d) AS violations
    """,
}


async def invariant_violations(today: date) -> dict[str, int]:
    """Violation count per invariant (all should be 0)."""
    results: dict[str, int] = {}
    for name, query in INVARIANTS.items():
        rows = await run_read(query, {"today": today})
        results[name] = rows[0]["violations"]
    return results
