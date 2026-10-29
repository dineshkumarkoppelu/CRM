// Schema initialisation (graph-schema.md). Idempotent: safe to run on every startup.
// One statement per block, separated by ";" and a blank line. Full-line "//" comments only.
// The runner executes each statement in its own auto-commit transaction.

// ---- Uniqueness constraints ----
CREATE CONSTRAINT sp_id_unique IF NOT EXISTS
FOR (n:SalesPerson) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT client_id_unique IF NOT EXISTS
FOR (n:Client) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT deal_id_unique IF NOT EXISTS
FOR (n:Deal) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT activity_id_unique IF NOT EXISTS
FOR (n:Activity) REQUIRE n.id IS UNIQUE;

CREATE CONSTRAINT domain_name_unique IF NOT EXISTS
FOR (n:Domain) REQUIRE n.name IS UNIQUE;

// ---- Range indexes ----
CREATE RANGE INDEX deal_status_idx IF NOT EXISTS
FOR (n:Deal) ON (n.status);

CREATE RANGE INDEX deal_stage_idx IF NOT EXISTS
FOR (n:Deal) ON (n.stage);

CREATE RANGE INDEX deal_expected_close_idx IF NOT EXISTS
FOR (n:Deal) ON (n.expected_close_date);

CREATE RANGE INDEX deal_closed_at_idx IF NOT EXISTS
FOR (n:Deal) ON (n.closed_at);

CREATE RANGE INDEX deal_created_at_idx IF NOT EXISTS
FOR (n:Deal) ON (n.created_at);

CREATE RANGE INDEX activity_date_idx IF NOT EXISTS
FOR (n:Activity) ON (n.date);

// ---- The 5 built-in domains (same order as app/core/domains.py) ----
// Descriptions and embeddings are added by domain_service.ensure_builtin_domains().
WITH ['AI', 'Cybersecurity', 'IoT', 'DevOps', 'Cloud Migration'] AS names
UNWIND range(0, size(names) - 1) AS i
MERGE (d:Domain {name: names[i]})
SET d.builtin = true, d.position = i;
