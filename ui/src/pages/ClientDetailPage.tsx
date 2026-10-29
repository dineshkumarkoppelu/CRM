import { Link, useNavigate, useParams } from "react-router-dom";

import { useClient } from "../api/hooks";
import type { Deal } from "../api/types";
import { DomainChip, StageLabel, StatusBadge } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Layout";
import { RepLink } from "../components/Links";
import { EmptyState, QueryState } from "../components/States";
import { formatDate, formatINR, SIZE_LABEL } from "../lib/format";

export function ClientDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const client = useClient(id);
  return (
    <div className="px-6 pt-5 pb-8">
      <nav className="mb-2 text-xs text-ink-muted">
        <Link to="/clients" className="link">
          Clients
        </Link>{" "}
        / {id}
      </nav>
      <QueryState query={client}>
        {(c) => {
          const won = c.deals.filter((d) => d.status === "WON");
          const open = c.deals.filter((d) => d.status === "OPEN");
          return (
            <div className="space-y-4">
              <div>
                <h1 className="text-lg font-semibold tracking-tight">{c.name}</h1>
                <p className="mt-0.5 text-[13px] text-ink-muted">
                  {c.industry} · {SIZE_LABEL[c.size]} · {c.region} · client since {formatDate(c.created_on)}
                </p>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Deals" value={String(c.deals.length)} />
                <Stat label="Open pipeline" value={formatINR(open.reduce((s, d) => s + d.value, 0))} />
                <Stat label="Won value" value={formatINR(won.reduce((s, d) => s + d.value, 0))} />
              </div>
              <Panel title="Deals">
                <DataTable<Deal>
                  rows={c.deals}
                  rowKey={(d) => d.id}
                  onRowClick={(d) => navigate(`/deals/${d.id}`)}
                  empty={<EmptyState title="No deals for this client" />}
                  columns={[
                    {
                      key: "deal",
                      header: "Deal",
                      render: (d) => (
                        <div>
                          <div className="font-medium">{d.title}</div>
                          <div className="text-xs text-ink-faint">{d.id}</div>
                        </div>
                      ),
                    },
                    { key: "domain", header: "Domain", render: (d) => <DomainChip domain={d.domain} /> },
                    { key: "stage", header: "Stage", render: (d) => <StageLabel stage={d.stage} /> },
                    { key: "status", header: "Status", render: (d) => <StatusBadge status={d.status} /> },
                    { key: "value", header: "Value", align: "right", render: (d) => formatINR(d.value) },
                    { key: "owner", header: "Owner", render: (d) => <RepLink id={d.owner_id} name={d.owner_name} /> },
                    { key: "created", header: "Created", className: "whitespace-nowrap", render: (d) => formatDate(d.created_at) },
                    { key: "closed", header: "Closed", className: "whitespace-nowrap", render: (d) => formatDate(d.closed_at) },
                  ]}
                />
              </Panel>
            </div>
          );
        }}
      </QueryState>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-xs text-ink-muted">{label}</div>
      <div className="num mt-0.5 text-[17px] font-semibold">{value}</div>
    </div>
  );
}
