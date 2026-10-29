import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import { useConfig, useDeals, useForecast, useSalesPerson, useUpdateSalesPerson } from "../api/hooks";
import type { Deal, ExpertiseRow, SalesPersonDetail } from "../api/types";
import { DomainChip, LoadGauge, StageLabel } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { Panel } from "../components/Layout";
import { ClientLink } from "../components/Links";
import { EmptyState, QueryState } from "../components/States";
import { domainColor } from "../lib/domains";
import { formatDate, formatDecimal, formatINR, formatMonth, formatPct } from "../lib/format";

export function RepProfilePage() {
  const { id } = useParams();
  const rep = useSalesPerson(id);
  return (
    <div className="px-6 pt-5 pb-8">
      <nav className="mb-2 text-xs text-ink-muted">
        <Link to="/heatmap" className="link">
          Sales people
        </Link>{" "}
        / {id}
      </nav>
      <QueryState query={rep}>{(r) => <RepView rep={r} />}</QueryState>
    </div>
  );
}

function RepView({ rep }: { rep: SalesPersonDetail }) {
  return (
    <div className="space-y-4">
      <RepHeader key={`${rep.id}-${rep.capacity}-${rep.active}`} rep={rep} />
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="space-y-4 xl:col-span-3">
          <ExpertisePanel rep={rep} />
          <OpenDealsPanel repId={rep.id} />
        </div>
        <div className="space-y-4 xl:col-span-2">
          <PeersPanel rep={rep} />
          <ForecastSlice repId={rep.id} />
        </div>
      </div>
    </div>
  );
}

function RepHeader({ rep }: { rep: SalesPersonDetail }) {
  const update = useUpdateSalesPerson();
  const [capacity, setCapacity] = useState(String(rep.capacity));
  const parsed = Number(capacity);
  const capacityValid = Number.isInteger(parsed) && parsed >= 1 && parsed <= 50;
  const full = rep.open_count >= rep.capacity;

  return (
    <div className="panel flex flex-wrap items-start justify-between gap-6 px-5 py-4">
      <div>
        <div className="flex items-center gap-2.5">
          <h1 className="text-lg font-semibold tracking-tight">{rep.name}</h1>
          <span className="text-xs text-ink-faint">{rep.id}</span>
          {!rep.active && <span className="rounded-sm bg-canvas px-1.5 py-0.5 text-xs text-ink-muted">Inactive</span>}
        </div>
        <p className="mt-0.5 text-[13px] text-ink-muted">
          {rep.region} · {rep.email} · joined {formatDate(rep.joined_on)}
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-6">
        <div>
          <div className="label">Open deals</div>
          <LoadGauge open={rep.open_count} capacity={rep.capacity} />
          <div className={`mt-0.5 text-xs ${full ? "text-lost" : "text-ink-muted"}`}>
            {full ? "At capacity: not eligible for new deals" : `Availability ${formatPct(rep.availability)}`}
          </div>
        </div>

        <form
          className="flex items-end gap-1.5"
          onSubmit={(e) => {
            e.preventDefault();
            if (capacityValid) update.mutate({ id: rep.id, changes: { capacity: parsed } });
          }}
        >
          <label>
            <span className="label">Capacity</span>
            <input
              className="input num w-20"
              type="number"
              min={1}
              max={50}
              value={capacity}
              onChange={(e) => setCapacity(e.target.value)}
            />
          </label>
          <button type="submit" className="btn" disabled={!capacityValid || parsed === rep.capacity || update.isPending}>
            Save
          </button>
        </form>

        <div>
          <div className="label">Status</div>
          <button
            type="button"
            role="switch"
            aria-checked={rep.active}
            disabled={update.isPending}
            onClick={() => update.mutate({ id: rep.id, changes: { active: !rep.active } })}
            className="inline-flex h-8 items-center gap-2 text-[13px]"
          >
            <span className={`relative h-5 w-9 rounded-full transition-colors ${rep.active ? "bg-accent" : "bg-line-strong"}`}>
              <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all ${rep.active ? "left-[18px]" : "left-0.5"}`} />
            </span>
            {rep.active ? "Active" : "Inactive"}
          </button>
        </div>
      </div>
      {update.error && <p className="w-full text-[13px] text-lost">{errorMessage(update.error)}</p>}
    </div>
  );
}

function ExpertisePanel({ rep }: { rep: SalesPersonDetail }) {
  const config = useConfig();
  const min = config.data?.expertise.min_deals_per_domain ?? 3;
  const months = config.data?.analytics.lookback_months ?? 12;
  return (
    <Panel
      title="Domain expertise"
      description={`Win rate on closed deals in the last ${months} months. Hatched bars have fewer than ${min} closed deals and do not count as expertise.`}
    >
      <div className="space-y-2.5 px-4 py-4">
        {rep.expertise.map((e) => (
          <ExpertiseBar key={e.domain} row={e} />
        ))}
      </div>
    </Panel>
  );
}

function ExpertiseBar({ row }: { row: ExpertiseRow }) {
  const color = domainColor(row.domain);
  const pct = (row.win_rate ?? 0) * 100;
  return (
    <div className="grid grid-cols-[130px_1fr_150px] items-center gap-3 text-[13px]">
      <span>{row.domain}</span>
      <div className="relative h-5 rounded-sm bg-canvas">
        {row.handled > 0 && (
          <div
            className={`absolute inset-y-0 left-0 rounded-sm ${row.qualifies ? "" : "hatch"}`}
            style={{ width: `${Math.max(pct, 1)}%`, backgroundColor: row.qualifies ? color : `${color}40` }}
          />
        )}
      </div>
      <span className="num text-xs text-ink-muted">
        {row.handled === 0 ? (
          "No closed deals"
        ) : (
          <>
            <span className={`text-[13px] font-medium ${row.qualifies ? "text-ink" : "text-ink-muted"}`}>{formatPct(row.win_rate)}</span> · {row.won}/
            {row.handled} won
          </>
        )}
      </span>
    </div>
  );
}

function PeersPanel({ rep }: { rep: SalesPersonDetail }) {
  const config = useConfig();
  const tolerance = config.data?.similarity.similarity_tolerance ?? 0.1;
  const minDomains = config.data?.similarity.similarity_min_domains ?? 3;
  return (
    <Panel
      title="Similar sales people"
      description={`Win rates within ${Math.round(tolerance * 100)} points in at least ${minDomains} shared domains. Used to borrow a track record (PEER fit).`}
    >
      {rep.similar_peers.length === 0 ? (
        <EmptyState title="No similar sales people">Nobody matches this rep's win-rate profile closely enough.</EmptyState>
      ) : (
        <ul className="divide-y divide-line">
          {rep.similar_peers.map((p) => (
            <li key={p.id} className="px-4 py-2.5">
              <div className="flex items-center justify-between gap-3">
                <Link to={`/reps/${p.id}`} className="link text-[13px] font-medium">
                  {p.name}
                </Link>
                <span className="num text-[13px]">
                  <span className="text-xs text-ink-muted">score </span>
                  {formatDecimal(p.score)}
                </span>
              </div>
              <div className="mt-1.5 flex flex-wrap gap-1">
                {p.matched_domains.map((d) => (
                  <DomainChip key={d} domain={d} />
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function OpenDealsPanel({ repId }: { repId: string }) {
  const navigate = useNavigate();
  const deals = useDeals({ owner_id: repId, status: "OPEN", limit: 200 });
  return (
    <Panel title="Open pipeline">
      <QueryState query={deals}>
        {(page) => (
          <DataTable<Deal>
            rows={page.items}
            rowKey={(d) => d.id}
            onRowClick={(d) => navigate(`/deals/${d.id}`)}
            empty={<EmptyState title="No open deals" />}
            columns={[
              { key: "deal", header: "Deal", render: (d) => <span className="font-medium">{d.title}</span> },
              { key: "client", header: "Client", render: (d) => <ClientLink id={d.client_id} name={d.client_name} /> },
              { key: "domain", header: "Domain", render: (d) => <DomainChip domain={d.domain} /> },
              { key: "stage", header: "Stage", render: (d) => <StageLabel stage={d.stage} /> },
              { key: "value", header: "Value", align: "right", render: (d) => formatINR(d.value) },
              { key: "close", header: "Expected close", className: "whitespace-nowrap", render: (d) => formatDate(d.expected_close_date) },
            ]}
          />
        )}
      </QueryState>
    </Panel>
  );
}

function ForecastSlice({ repId }: { repId: string }) {
  const forecast = useForecast();
  return (
    <Panel title={forecast.data ? `Forecast · ${formatMonth(forecast.data.month)}` : "Forecast"}>
      <QueryState query={forecast}>
        {(f) => {
          const row = f.by_rep.find((r) => r.sales_person_id === repId);
          if (!row) return <EmptyState title="Not in this month's forecast">Only active sales people are forecast.</EmptyState>;
          return (
            <div>
              <div className="grid grid-cols-4 gap-px border-b border-line bg-line">
                {[
                  ["Expected", formatDecimal(row.expected_conversions)],
                  ["Commit", String(row.commit)],
                  ["Best case", String(row.best_case)],
                  ["Converted", String(row.converted_so_far)],
                ].map(([label, value]) => (
                  <div key={label} className="bg-panel px-3 py-2.5">
                    <div className="text-xs text-ink-muted">{label}</div>
                    <div className="num text-[17px] font-semibold">{value}</div>
                  </div>
                ))}
              </div>
              {row.clients.length === 0 ? (
                <EmptyState title="No open deals expected to close this month" />
              ) : (
                <ul className="divide-y divide-line">
                  {row.clients.map((c) => (
                    <li key={c.client_id} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]">
                      <ClientLink id={c.client_id} name={c.client_name} />
                      <span className="num">{formatPct(c.probability)}</span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="px-4 py-2 text-xs text-ink-muted">Expected revenue {formatINR(row.expected_revenue)}</div>
            </div>
          );
        }}
      </QueryState>
    </Panel>
  );
}
