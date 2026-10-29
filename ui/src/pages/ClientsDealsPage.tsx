import { useDeferredValue, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";

import { errorMessage } from "../api/client";
import { useClients, useDeals, useDomains, useMoveStage, useSalesPeople } from "../api/hooks";
import type { Client, Deal, DealFilters, DealStatus, Domain, Stage, StageAction } from "../api/types";
import { DomainChip, StageLabel, StatusBadge } from "../components/Badges";
import { DataTable, Pager } from "../components/DataTable";
import { PageHeader, Panel, Tabs } from "../components/Layout";
import { ClientLink, RepLink } from "../components/Links";
import { EmptyState, QueryState } from "../components/States";
import { STAGE_LABEL, STAGES } from "../lib/domains";
import { formatDate, formatINR, formatINRCompact, SIZE_LABEL } from "../lib/format";
import { NewClientDealDrawer } from "./NewClientDealDrawer";

const PAGE_SIZE = 50;

export function ClientsDealsPage() {
  const { pathname } = useLocation();
  const navigate = useNavigate();
  const [drawer, setDrawer] = useState(false);
  const tab = pathname.startsWith("/clients") ? "clients" : "deals";
  return (
    <div className="pb-8">
      <PageHeader
        title="Clients & Deals"
        description="Every opportunity in the CRM. New deals are routed to the best available sales person."
        actions={
          <button type="button" className="btn btn-primary" onClick={() => setDrawer(true)}>
            New client and deal
          </button>
        }
      />
      <div className="px-6">
        <div className="mb-3">
          <Tabs
            value={tab}
            onChange={(t) => navigate(t === "clients" ? "/clients" : "/deals")}
            options={[
              { value: "deals", label: "Deals" },
              { value: "clients", label: "Clients" },
            ]}
          />
        </div>
        {tab === "deals" ? <DealsTab /> : <ClientsTab />}
      </div>
      <NewClientDealDrawer open={drawer} onClose={() => setDrawer(false)} />
    </div>
  );
}

// ---------------------------------------------------------------- deals

function DealsTab() {
  const [filters, setFilters] = useState<DealFilters>({});
  const [offset, setOffset] = useState(0);
  const [view, setView] = useState<"table" | "board">("table");
  const reps = useSalesPeople();
  const domains = useDomains();

  const update = (patch: Partial<DealFilters>) => {
    setFilters((f) => ({ ...f, ...patch }));
    setOffset(0);
  };
  const active = Object.values(filters).some((v) => v !== undefined && v !== "");

  return (
    <div className="space-y-3">
      <div className="panel flex flex-wrap items-end gap-3 px-3 py-2.5">
        {view === "table" && (
          <Filter label="Status">
            <select className="input w-28" value={filters.status ?? ""} onChange={(e) => update({ status: (e.target.value || undefined) as DealStatus | undefined })}>
              <option value="">All</option>
              <option value="OPEN">Open</option>
              <option value="WON">Won</option>
              <option value="LOST">Lost</option>
            </select>
          </Filter>
        )}
        <Filter label="Stage">
          <select className="input w-32" value={filters.stage ?? ""} onChange={(e) => update({ stage: (e.target.value || undefined) as Stage | undefined })}>
            <option value="">All</option>
            {STAGES.map((s) => (
              <option key={s} value={s}>
                {STAGE_LABEL[s]}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Domain">
          <select className="input w-40" value={filters.domain ?? ""} onChange={(e) => update({ domain: (e.target.value || undefined) as Domain | undefined })}>
            <option value="">All</option>
            {domains.data?.map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </Filter>
        <Filter label="Owner">
          <select className="input w-44" value={filters.owner_id ?? ""} onChange={(e) => update({ owner_id: e.target.value || undefined })}>
            <option value="">All</option>
            {reps.data?.items.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </Filter>
        <Filter label="Closing month">
          <input type="month" className="input w-40" value={filters.closing_month ?? ""} onChange={(e) => update({ closing_month: e.target.value || undefined })} />
        </Filter>
        {active && (
          <button type="button" className="btn btn-ghost btn-sm mb-0.5" onClick={() => update({ status: undefined, stage: undefined, domain: undefined, owner_id: undefined, closing_month: undefined })}>
            Clear filters
          </button>
        )}
        <div className="ml-auto">
          <Tabs
            value={view}
            onChange={setView}
            options={[
              { value: "table", label: "Table" },
              { value: "board", label: "Board (open)" },
            ]}
          />
        </div>
      </div>
      {view === "table" ? <DealsTable filters={filters} offset={offset} onOffset={setOffset} /> : <DealsBoard filters={filters} />}
    </div>
  );
}

function Filter({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="label">{label}</span>
      {children}
    </label>
  );
}

function DealsTable({ filters, offset, onOffset }: { filters: DealFilters; offset: number; onOffset: (o: number) => void }) {
  const navigate = useNavigate();
  const deals = useDeals({ ...filters, limit: PAGE_SIZE, offset });
  return (
    <Panel>
      <QueryState query={deals}>
        {(page) => (
          <>
            <DataTable<Deal>
              rows={page.items}
              rowKey={(d) => d.id}
              onRowClick={(d) => navigate(`/deals/${d.id}`)}
              empty={<EmptyState title="No deals match these filters" />}
              columns={[
                {
                  key: "deal",
                  header: "Deal",
                  render: (d) => (
                    <div className="max-w-[320px]">
                      <div className="truncate font-medium">{d.title}</div>
                      <div className="text-xs text-ink-faint">{d.id}</div>
                    </div>
                  ),
                },
                { key: "client", header: "Client", render: (d) => <ClientLink id={d.client_id} name={d.client_name} /> },
                { key: "domain", header: "Domain", render: (d) => <DomainChip domain={d.domain} /> },
                { key: "stage", header: "Stage", render: (d) => <StageLabel stage={d.stage} /> },
                { key: "status", header: "Status", render: (d) => <StatusBadge status={d.status} /> },
                { key: "value", header: "Value", align: "right", render: (d) => formatINR(d.value) },
                { key: "owner", header: "Owner", render: (d) => <RepLink id={d.owner_id} name={d.owner_name} /> },
                {
                  key: "close",
                  header: "Expected close",
                  render: (d) => (d.closed_at ? <span className="text-ink-muted">Closed {formatDate(d.closed_at)}</span> : formatDate(d.expected_close_date)),
                },
              ]}
            />
            <Pager total={page.total} offset={offset} limit={PAGE_SIZE} onChange={onOffset} />
          </>
        )}
      </QueryState>
    </Panel>
  );
}

function DealsBoard({ filters }: { filters: DealFilters }) {
  const deals = useDeals({ ...filters, status: "OPEN", limit: 200, offset: 0 });
  const move = useMoveStage();
  const pendingId = move.isPending ? move.variables?.dealId : undefined;
  const act = (dealId: string, action: StageAction) => move.mutate({ dealId, action });

  return (
    <div>
      {move.error && <p className="mb-2 rounded border border-lost/25 bg-lost-soft px-3 py-2 text-[13px] text-lost">{errorMessage(move.error)}</p>}
      <QueryState query={deals}>
        {(page) => (
          <>
            {page.total > page.items.length && (
              <p className="mb-2 text-xs text-ink-muted">
                Showing the {page.items.length} most recent of {page.total} open deals. Use the filters to narrow down.
              </p>
            )}
            <div className="grid grid-cols-4 gap-3">
              {STAGES.map((stage) => {
                const column = page.items.filter((d) => d.stage === stage);
                return (
                  <div key={stage} className="flex min-h-40 flex-col rounded-md border border-line bg-canvas/60">
                    <div className="flex items-center justify-between border-b border-line px-3 py-2">
                      <StageLabel stage={stage} />
                      <span className="num text-xs text-ink-muted">
                        {column.length} · {formatINRCompact(column.reduce((s, d) => s + d.value, 0))}
                      </span>
                    </div>
                    <div className="flex max-h-[calc(100vh-280px)] flex-col gap-2 overflow-y-auto p-2">
                      {column.length === 0 && <p className="px-1 py-3 text-center text-xs text-ink-faint">No deals</p>}
                      {column.map((d) => (
                        <BoardCard key={d.id} deal={d} busy={pendingId === d.id} disabled={Boolean(pendingId)} onAction={act} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          </>
        )}
      </QueryState>
    </div>
  );
}

function BoardCard({
  deal,
  busy,
  disabled,
  onAction,
}: {
  deal: Deal;
  busy: boolean;
  disabled: boolean;
  onAction: (dealId: string, action: StageAction) => void;
}) {
  const navigate = useNavigate();
  const last = deal.stage === "NEGOTIATION";
  return (
    <div className={`panel px-2.5 py-2 ${busy ? "opacity-60" : ""}`}>
      <button type="button" className="block w-full text-left" onClick={() => navigate(`/deals/${deal.id}`)}>
        <div className="text-[13px] leading-snug font-medium hover:text-accent">{deal.title}</div>
        <div className="mt-0.5 truncate text-xs text-ink-muted">{deal.client_name}</div>
      </button>
      <div className="mt-2 flex items-center justify-between gap-2">
        <DomainChip domain={deal.domain} />
        <span className="num text-xs font-medium">{formatINRCompact(deal.value)}</span>
      </div>
      <div className="mt-1.5 flex items-center justify-between text-xs text-ink-muted">
        <RepLink id={deal.owner_id} name={deal.owner_name} />
        <span>Closes {formatDate(deal.expected_close_date)}</span>
      </div>
      <div className="mt-2 flex gap-1.5 border-t border-line pt-2">
        {last ? (
          <button type="button" className="btn btn-sm flex-1 border-won/40 text-won" disabled={disabled} onClick={() => onAction(deal.id, "WIN")}>
            Mark won
          </button>
        ) : (
          <button type="button" className="btn btn-sm flex-1" disabled={disabled} onClick={() => onAction(deal.id, "ADVANCE")}>
            Advance
          </button>
        )}
        <button type="button" className="btn btn-sm text-lost" disabled={disabled} onClick={() => onAction(deal.id, "LOSE")}>
          Lost
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- clients

function ClientsTab() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const query = useDeferredValue(search.trim());
  const clients = useClients(query, PAGE_SIZE, offset);
  return (
    <div className="space-y-3">
      <div className="panel px-3 py-2.5">
        <input
          className="input max-w-sm"
          type="search"
          placeholder="Search clients by name"
          aria-label="Search clients by name"
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setOffset(0);
          }}
        />
      </div>
      <Panel>
        <QueryState query={clients}>
          {(page) => (
            <>
              <DataTable<Client>
                rows={page.items}
                rowKey={(c) => c.id}
                onRowClick={(c) => navigate(`/clients/${c.id}`)}
                empty={<EmptyState title="No clients found">Try a different name.</EmptyState>}
                columns={[
                  { key: "name", header: "Client", render: (c) => <span className="font-medium">{c.name}</span> },
                  { key: "id", header: "ID", render: (c) => <span className="text-ink-muted">{c.id}</span> },
                  { key: "industry", header: "Industry", render: (c) => c.industry },
                  { key: "size", header: "Size", render: (c) => SIZE_LABEL[c.size] },
                  { key: "region", header: "Region", render: (c) => c.region },
                  { key: "created", header: "Client since", className: "whitespace-nowrap", render: (c) => formatDate(c.created_on) },
                ]}
              />
              <Pager total={page.total} offset={offset} limit={PAGE_SIZE} onChange={setOffset} />
            </>
          )}
        </QueryState>
      </Panel>
    </div>
  );
}
