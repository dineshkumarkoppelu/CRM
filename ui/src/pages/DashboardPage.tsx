import { Fragment, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  useBacktest,
  useConfig,
  useDomainTrend,
  useForecast,
  useKpis,
  useLeaderboard,
  usePipeline,
  useStalled,
} from "../api/hooks";
import type { ForecastRep, PipelineRep, ProbabilitySource, StalledDeal } from "../api/types";
import { DomainChip, StageLabel } from "../components/Badges";
import { DataTable } from "../components/DataTable";
import { KpiCard } from "../components/KpiCard";
import { PageHeader, Panel, Tabs } from "../components/Layout";
import { DealLink, RepLink } from "../components/Links";
import { InfoTip } from "../components/Overlay";
import { EmptyState, QueryState } from "../components/States";
import { ACCENT, domainColor, INK_MUTED, LINE, STAGE_COLOR, STAGE_LABEL, STAGES } from "../lib/domains";
import { formatDate, formatDecimal, formatINR, formatINRCompact, formatInt, formatMonth, formatPct } from "../lib/format";

const AXIS = { fontSize: 11, fill: INK_MUTED };
const TOOLTIP_STYLE = { fontSize: 12, borderRadius: 4, borderColor: LINE };

export function DashboardPage() {
  return (
    <div className="pb-8">
      <PageHeader title="Dashboard" description="Team performance, this month's conversion forecast and pipeline health." />
      <div className="space-y-4 px-6">
        <KpiRow />
        <ForecastPanel />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
          <PipelinePanel />
          <BacktestPanel />
        </div>
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
          <DomainTrendPanel />
          <LeaderboardPanel />
        </div>
        <StalledPanel />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- KPIs

function KpiRow() {
  const kpis = useKpis();
  const config = useConfig();
  const months = config.data?.analytics.lookback_months ?? 12;
  return (
    <QueryState query={kpis}>
      {(k) => (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
          <KpiCard label="Open pipeline" value={formatINRCompact(k.open_value)} hint={`${formatInt(k.open_deals)} open deals`} />
          <KpiCard label="Won this month" value={formatInt(k.won_this_month)} hint={`${formatInt(k.clients_converted_this_month)} clients converted`} />
          <KpiCard label="Win rate" value={formatPct(k.win_rate_window)} hint={`Closed deals, last ${months} months`} />
          <KpiCard label="Average sales cycle" value={k.avg_cycle_days == null ? "—" : `${formatDecimal(k.avg_cycle_days, 1)} days`} hint="Won deals" />
          <KpiCard label="Average won value" value={formatINRCompact(k.avg_won_value)} hint={`Last ${months} months`} />
          <KpiCard
            label="Stalled deals"
            value={formatInt(k.stalled_count)}
            hint={`No activity for ${config.data?.analytics.stalled_days ?? 21}+ days`}
          />
        </div>
      )}
    </QueryState>
  );
}

// ---------------------------------------------------------------- forecast

const SOURCE_LABEL: Record<ProbabilitySource, string> = {
  REP_DOMAIN_STAGE: "Rep's own history",
  TEAM_DOMAIN_STAGE: "Team, same domain",
  TEAM_STAGE: "Team, all domains",
};

function ForecastPanel() {
  const forecast = useForecast();
  const config = useConfig();
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const commit = config.data?.forecast.forecast_commit_threshold ?? 0.7;
  const best = config.data?.forecast.forecast_best_case_threshold ?? 0.3;

  const toggle = (id: string) =>
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Panel
      title={forecast.data ? `Conversion forecast · ${formatMonth(forecast.data.month)}` : "Conversion forecast"}
      description={`Clients expected to convert this month. Commit: client probability ≥ ${formatPct(commit)}. Best case: ≥ ${formatPct(best)}. Expand a row for client detail.`}
    >
      <QueryState query={forecast}>
        {(f) => (
          <div className="overflow-x-auto">
            <table className="table">
              <thead>
                <tr>
                  <th className="w-8" />
                  <th>Sales person</th>
                  <th className="text-right">Expected conversions</th>
                  <th className="text-right">Commit</th>
                  <th className="text-right">Best case</th>
                  <th className="text-right">Converted so far</th>
                  <th className="text-right">Expected revenue</th>
                  <th className="text-right">Clients in scope</th>
                </tr>
              </thead>
              <tbody>
                {f.by_rep.map((rep) => (
                  <ForecastRow key={rep.sales_person_id} rep={rep} open={expanded.has(rep.sales_person_id)} onToggle={toggle} />
                ))}
              </tbody>
              <tfoot>
                <tr className="bg-canvas/70 font-semibold">
                  <td className="px-3 py-2" />
                  <td className="px-3 py-2">Team</td>
                  <td className="num px-3 py-2 text-right">{formatDecimal(f.team.expected_conversions)}</td>
                  <td className="num px-3 py-2 text-right">{f.team.commit}</td>
                  <td className="num px-3 py-2 text-right">{f.team.best_case}</td>
                  <td className="num px-3 py-2 text-right">{f.team.converted_so_far}</td>
                  <td className="num px-3 py-2 text-right">{formatINR(f.team.expected_revenue)}</td>
                  <td className="num px-3 py-2 text-right">{f.by_rep.reduce((n, r) => n + r.clients.length, 0)}</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </QueryState>
    </Panel>
  );
}

function ForecastRow({ rep, open, onToggle }: { rep: ForecastRep; open: boolean; onToggle: (id: string) => void }) {
  const hasClients = rep.clients.length > 0;
  return (
    <Fragment>
      <tr className={hasClients ? "cursor-pointer hover:bg-canvas/70" : ""} onClick={hasClients ? () => onToggle(rep.sales_person_id) : undefined}>
        <td className="text-ink-faint">
          {hasClients && (
            <svg width="10" height="10" viewBox="0 0 10 10" className={`transition-transform ${open ? "rotate-90" : ""}`} aria-hidden>
              <path d="M3.5 2 6.5 5 3.5 8" fill="none" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          )}
        </td>
        <td>
          <RepLink id={rep.sales_person_id} name={rep.name} />
        </td>
        <td className="num text-right font-medium">{formatDecimal(rep.expected_conversions)}</td>
        <td className="num text-right">{rep.commit}</td>
        <td className="num text-right">{rep.best_case}</td>
        <td className="num text-right">{rep.converted_so_far}</td>
        <td className="num text-right">{formatINR(rep.expected_revenue)}</td>
        <td className="num text-right text-ink-muted">{rep.clients.length}</td>
      </tr>
      {open && (
        <tr>
          <td />
          <td colSpan={7} className="bg-canvas/50 py-3">
            <table className="w-full text-[13px]">
              <thead>
                <tr className="text-xs text-ink-muted">
                  <th className="pb-1.5 text-left font-medium">Client</th>
                  <th className="pb-1.5 text-left font-medium">Probability</th>
                  <th className="pb-1.5 text-left font-medium">Deals (stage · value · win probability · based on)</th>
                </tr>
              </thead>
              <tbody>
                {rep.clients.map((c) => (
                  <tr key={c.client_id} className="align-top">
                    <td className="py-1 pr-4">{c.client_name}</td>
                    <td className="py-1 pr-4">
                      <ProbabilityBar value={c.probability} />
                    </td>
                    <td className="py-1">
                      {c.deals.map((d) => (
                        <div key={d.deal_id} className="flex flex-wrap items-center gap-x-3 text-xs text-ink-muted">
                          <DealLink id={d.deal_id} />
                          <StageLabel stage={d.stage} />
                          <span className="num">{formatINR(d.value)}</span>
                          <span className="num">{formatPct(d.p_deal)}</span>
                          <span>{SOURCE_LABEL[d.probability_source]}</span>
                        </div>
                      ))}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </td>
        </tr>
      )}
    </Fragment>
  );
}

function ProbabilityBar({ value }: { value: number }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="relative h-1.5 w-20 rounded-full bg-line">
        <span className="absolute inset-y-0 left-0 rounded-full bg-accent" style={{ width: `${value * 100}%` }} />
      </span>
      <span className="num">{formatPct(value)}</span>
    </span>
  );
}

// ---------------------------------------------------------------- pipeline

function PipelinePanel() {
  const pipeline = usePipeline();
  return (
    <Panel title="Open pipeline by sales person" description="Open deals by stage. The vertical mark is each rep's capacity.">
      <QueryState query={pipeline} isEmpty={(p) => p.reps.length === 0} empty={<EmptyState title="No active sales people" />}>
        {(p) => <PipelineChart reps={p.reps} unassigned={p.unassigned_open_count} />}
      </QueryState>
    </Panel>
  );
}

function PipelineChart({ reps, unassigned }: { reps: PipelineRep[]; unassigned: number }) {
  const max = Math.max(1, ...reps.map((r) => Math.max(r.capacity, r.open_count)));
  return (
    <div className="px-4 py-3">
      <div className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-ink-muted">
        {STAGES.map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[2px]" style={{ backgroundColor: STAGE_COLOR[s] }} />
            {STAGE_LABEL[s]}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-3 w-0.5 bg-ink" />
          Capacity
        </span>
      </div>
      <div className="space-y-1.5">
        {reps.map((r) => {
          const full = r.open_count >= r.capacity;
          return (
            <div key={r.sales_person_id} className="grid grid-cols-[132px_1fr_44px] items-center gap-3 text-[13px]">
              <span className="truncate">
                <RepLink id={r.sales_person_id} name={r.name} />
              </span>
              <div className="relative h-4">
                <div className="absolute inset-y-0.5 left-0 right-0 rounded-sm bg-canvas" />
                <div className="absolute inset-y-0.5 left-0 flex overflow-hidden rounded-sm" style={{ width: `${(r.open_count / max) * 100}%` }}>
                  {STAGES.map((s) =>
                    r.by_stage[s] > 0 ? (
                      <span
                        key={s}
                        title={`${STAGE_LABEL[s]}: ${r.by_stage[s]}`}
                        style={{ flexGrow: r.by_stage[s], backgroundColor: STAGE_COLOR[s] }}
                      />
                    ) : null,
                  )}
                </div>
                <div
                  className="absolute -inset-y-0.5 w-0.5 bg-ink"
                  style={{ left: `calc(${(r.capacity / max) * 100}% - 1px)` }}
                  title={`Capacity ${r.capacity}`}
                />
              </div>
              <span className={`num text-right ${full ? "font-medium text-lost" : "text-ink-muted"}`}>
                {r.open_count}/{r.capacity}
              </span>
            </div>
          );
        })}
      </div>
      {unassigned > 0 && (
        <p className="mt-3 text-xs text-warn">
          {unassigned} open {unassigned === 1 ? "deal has" : "deals have"} no owner.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- back-test

function BacktestPanel() {
  const backtest = useBacktest();
  return (
    <Panel
      title={backtest.data ? `Forecast back-test · ${formatMonth(backtest.data.month)}` : "Forecast back-test"}
      description={backtest.data ? `Forecast rebuilt as of ${formatDate(backtest.data.asof)}, compared with clients actually converted.` : undefined}
      actions={
        backtest.data && (
          <InfoTip label="Limitations">
            <ul className="list-disc space-y-1 pl-4">
              {backtest.data.limitations.map((l) => (
                <li key={l}>{l}</li>
              ))}
            </ul>
          </InfoTip>
        )
      }
    >
      <QueryState query={backtest}>
        {(b) => (
          <div className="px-2 pt-3 pb-2">
            <div className="mb-2 flex gap-6 px-2 text-[13px]">
              <span>
                <span className="text-ink-muted">Team predicted </span>
                <span className="num font-semibold">{formatDecimal(b.team.predicted_expected, 1)}</span>
              </span>
              <span>
                <span className="text-ink-muted">Actual </span>
                <span className="num font-semibold">{b.team.actual}</span>
              </span>
              <span>
                <span className="text-ink-muted">Mean absolute error per rep </span>
                <span className="num font-semibold">{formatDecimal(b.mean_abs_error)}</span>
              </span>
            </div>
            <ResponsiveContainer width="100%" height={250}>
              <BarChart
                data={b.by_rep.map((r) => ({ name: r.name.split(" ")[0], Predicted: r.predicted_expected, Actual: r.actual }))}
                margin={{ top: 4, right: 8, bottom: 0, left: -18 }}
                barGap={1}
              >
                <CartesianGrid stroke={LINE} vertical={false} />
                <XAxis dataKey="name" tick={AXIS} tickLine={false} axisLine={{ stroke: LINE }} interval={0} angle={-35} textAnchor="end" height={48} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} cursor={{ fill: "#f0f2f5" }} />
                <Legend wrapperStyle={{ fontSize: 12 }} iconSize={10} />
                <Bar dataKey="Predicted" isAnimationActive={false} fill="#9fb1cc" radius={[2, 2, 0, 0]} />
                <Bar dataKey="Actual" isAnimationActive={false} fill={ACCENT} radius={[2, 2, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </QueryState>
    </Panel>
  );
}

// ---------------------------------------------------------------- trend + leaderboard

function DomainTrendPanel() {
  const trend = useDomainTrend();
  return (
    <Panel title="New deals by domain" description="Deals created per month, last 12 months." className="xl:col-span-3">
      <QueryState query={trend}>
        {(t) => (
          <div className="px-2 pt-3 pb-2">
            <ResponsiveContainer width="100%" height={260}>
              <LineChart
                data={t.months.map((m, i) => ({
                  month: formatMonth(m, true),
                  ...Object.fromEntries(t.series.map((s) => [s.domain, s.counts[i]])),
                }))}
                margin={{ top: 4, right: 12, bottom: 0, left: -18 }}
              >
                <CartesianGrid stroke={LINE} vertical={false} />
                <XAxis dataKey="month" tick={AXIS} tickLine={false} axisLine={{ stroke: LINE }} />
                <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Legend wrapperStyle={{ fontSize: 12 }} iconSize={10} />
                {t.series.map((s) => (
                  <Line key={s.domain} type="monotone" dataKey={s.domain} stroke={domainColor(s.domain)} strokeWidth={1.75} dot={false} isAnimationActive={false} />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </QueryState>
    </Panel>
  );
}

function LeaderboardPanel() {
  const leaderboard = useLeaderboard();
  const [period, setPeriod] = useState<"month" | "quarter">("month");
  return (
    <Panel
      title="Leaderboard"
      description="Clients converted, then won value."
      className="xl:col-span-2"
      actions={
        <Tabs
          value={period}
          onChange={setPeriod}
          options={[
            { value: "month", label: "This month" },
            { value: "quarter", label: "This quarter" },
          ]}
        />
      }
    >
      <QueryState query={leaderboard}>
        {(l) => (
          <DataTable
            rows={l[period].slice(0, 10)}
            rowKey={(r) => r.sales_person_id}
            columns={[
              { key: "rank", header: "#", render: (r) => <span className="num text-ink-muted">{l[period].indexOf(r) + 1}</span> },
              { key: "rep", header: "Sales person", render: (r) => <RepLink id={r.sales_person_id} name={r.name} /> },
              { key: "clients", header: "Clients", align: "right", render: (r) => r.clients_converted },
              { key: "value", header: "Won value", align: "right", render: (r) => formatINRCompact(r.won_value) },
            ]}
          />
        )}
      </QueryState>
    </Panel>
  );
}

// ---------------------------------------------------------------- stalled

function StalledPanel() {
  const stalled = useStalled();
  const config = useConfig();
  const navigate = useNavigate();
  return (
    <Panel title="Stalled deals" description={`Open deals with no activity for more than ${config.data?.analytics.stalled_days ?? 21} days.`}>
      <QueryState query={stalled} isEmpty={(s) => s.length === 0} empty={<EmptyState title="No stalled deals" />}>
        {(rows) => (
          <DataTable<StalledDeal>
            rows={rows}
            rowKey={(r) => r.deal_id}
            onRowClick={(r) => navigate(`/deals/${r.deal_id}`)}
            columns={[
              {
                key: "deal",
                header: "Deal",
                render: (r) => (
                  <div>
                    <div className="font-medium">{r.title}</div>
                    <div className="text-xs text-ink-faint">{r.deal_id}</div>
                  </div>
                ),
              },
              { key: "client", header: "Client", render: (r) => r.client_name },
              { key: "owner", header: "Owner", render: (r) => <RepLink id={r.owner_id} name={r.owner_name} /> },
              { key: "domain", header: "Domain", render: (r) => <DomainChip domain={r.domain} /> },
              { key: "stage", header: "Stage", render: (r) => <StageLabel stage={r.stage} /> },
              { key: "last", header: "Last activity", className: "whitespace-nowrap", render: (r) => formatDate(r.last_activity_date) },
              {
                key: "days",
                header: "Days idle",
                align: "right",
                render: (r) => <span className="font-medium text-lost">{r.days_since_activity}</span>,
              },
            ]}
          />
        )}
      </QueryState>
    </Panel>
  );
}
