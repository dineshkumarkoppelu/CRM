import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { useConfig, useHeatmap, useSimilarityCompare } from "../api/hooks";
import type { Domain, Heatmap, HeatmapCell, SimilarityCompareRow } from "../api/types";
import { DomainChip } from "../components/Badges";
import { PageHeader, Panel, Tabs } from "../components/Layout";
import { EmptyState, Loading, QueryState } from "../components/States";
import { formatDecimal, formatPct } from "../lib/format";

type SortKey = "id" | "name" | Domain;

/** White -> accent blue, by win rate 0..1. */
function heatColor(rate: number): string {
  const from = [244, 246, 250];
  const to = [31, 79, 153];
  const t = Math.max(0, Math.min(1, rate));
  const [r, g, b] = from.map((f, i) => Math.round(f + (to[i] - f) * t));
  return `rgb(${r}, ${g}, ${b})`;
}

export function HeatmapPage() {
  const [tab, setTab] = useState<"winrates" | "similarity">("winrates");
  return (
    <div className="pb-8">
      <PageHeader
        title="Heatmap"
        description="Win rate of every sales person in every domain, computed live from closed deals."
        actions={
          <Tabs
            value={tab}
            onChange={setTab}
            options={[
              { value: "winrates", label: "Win rates" },
              { value: "similarity", label: "Similarity (rule vs GDS)" },
            ]}
          />
        }
      />
      <div className="px-6">{tab === "winrates" ? <WinRateGrid /> : <SimilarityTable />}</div>
    </div>
  );
}

function WinRateGrid() {
  const heatmap = useHeatmap();
  const config = useConfig();
  const min = config.data?.expertise.min_deals_per_domain ?? 3;
  const months = config.data?.analytics.lookback_months ?? 12;
  return (
    <Panel>
      <QueryState query={heatmap} isEmpty={(h) => h.reps.length === 0} empty={<EmptyState title="No sales people" />}>
        {(h) => <Grid heatmap={h} min={min} months={months} />}
      </QueryState>
    </Panel>
  );
}

function Grid({ heatmap, min, months }: { heatmap: Heatmap; min: number; months: number }) {
  const [sort, setSort] = useState<{ key: SortKey; desc: boolean }>({ key: "id", desc: false });
  const cells = useMemo(() => {
    const map = new Map<string, HeatmapCell>();
    for (const c of heatmap.cells) map.set(`${c.sales_person_id}|${c.domain}`, c);
    return map;
  }, [heatmap]);

  const reps = useMemo(() => {
    const rows = [...heatmap.reps];
    rows.sort((a, b) => {
      if (sort.key === "id") return sort.desc ? b.id.localeCompare(a.id) : a.id.localeCompare(b.id);
      if (sort.key === "name") return sort.desc ? b.name.localeCompare(a.name) : a.name.localeCompare(b.name);
      const ra = cells.get(`${a.id}|${sort.key}`)?.win_rate ?? null;
      const rb = cells.get(`${b.id}|${sort.key}`)?.win_rate ?? null;
      if (ra === null && rb === null) return a.id.localeCompare(b.id);
      if (ra === null) return 1; // no data always last
      if (rb === null) return -1;
      return sort.desc ? rb - ra || a.id.localeCompare(b.id) : ra - rb || a.id.localeCompare(b.id);
    });
    return rows;
  }, [heatmap, cells, sort]);

  const sortBy = (key: SortKey) =>
    setSort((s) => (s.key === key ? { key, desc: !s.desc } : { key, desc: key !== "id" && key !== "name" }));
  const arrow = (key: SortKey) => (sort.key === key ? (sort.desc ? " ↓" : " ↑") : "");

  return (
    <div>
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[13px]">
          <thead>
            <tr>
              <th className="border-b border-line px-3 py-2 text-left text-xs font-medium text-ink-muted">
                <button type="button" className="hover:text-ink" onClick={() => sortBy("name")}>
                  Sales person{arrow("name")}
                </button>
              </th>
              {heatmap.domains.map((d) => (
                <th key={d} className="border-b border-line px-1 py-2 text-xs font-medium text-ink-muted">
                  <button type="button" className="hover:text-ink" onClick={() => sortBy(d)} title={`Sort by ${d} win rate`}>
                    {d}
                    {arrow(d)}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {reps.map((rep) => (
              <tr key={rep.id}>
                <td className="border-b border-line px-3 py-1 whitespace-nowrap">
                  <Link to={`/reps/${rep.id}`} className="link">
                    {rep.name}
                  </Link>
                  <span className="ml-2 text-xs text-ink-faint">{rep.id}</span>
                </td>
                {heatmap.domains.map((d) => {
                  const cell = cells.get(`${rep.id}|${d}`);
                  return (
                    <td key={d} className="border-b border-line p-1">
                      {cell && <HeatCell cell={cell} repName={rep.name} min={min} />}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line px-4 py-3 text-xs text-ink-muted">
        <span className="inline-flex items-center gap-2">
          0%
          <span className="h-2.5 w-32 rounded-sm" style={{ background: `linear-gradient(90deg, ${heatColor(0)}, ${heatColor(1)})` }} />
          100%
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="hatch h-3.5 w-6 rounded-sm border border-line" />
          Fewer than {min} closed deals: does not qualify as expertise
        </span>
        <span>Cells show won / closed deals in the last {months} months. Click a column header to sort.</span>
      </div>
    </div>
  );
}

function HeatCell({ cell, repName, min }: { cell: HeatmapCell; repName: string; min: number }) {
  const title =
    cell.handled === 0
      ? `${repName} · ${cell.domain}: no closed deals`
      : `${repName} · ${cell.domain}: ${cell.won} won of ${cell.handled} closed (${formatPct(cell.win_rate)})${
          cell.qualifies ? "" : `, below the ${min}-deal minimum`
        }`;
  if (cell.handled === 0) {
    return <div title={title} className="flex h-11 items-center justify-center rounded-sm bg-canvas text-xs text-ink-faint">—</div>;
  }
  const rate = cell.win_rate ?? 0;
  if (!cell.qualifies) {
    return (
      <div title={title} className="hatch flex h-11 flex-col items-center justify-center rounded-sm border border-line text-ink-muted">
        <span className="num text-[13px]">{formatPct(rate)}</span>
        <span className="num text-[11px]">
          {cell.won}/{cell.handled}
        </span>
      </div>
    );
  }
  const dark = rate > 0.5;
  return (
    <div
      title={title}
      className={`flex h-11 flex-col items-center justify-center rounded-sm ${dark ? "text-white" : "text-ink"}`}
      style={{ backgroundColor: heatColor(rate) }}
    >
      <span className="num text-[13px] font-semibold">{formatPct(rate)}</span>
      <span className={`num text-[11px] ${dark ? "text-white/80" : "text-ink-muted"}`}>
        {cell.won}/{cell.handled}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------- similarity (Phase 7)

function SimilarityTable() {
  const compare = useSimilarityCompare(true);
  const heatmap = useHeatmap();
  const config = useConfig();
  const names = useMemo(() => new Map(heatmap.data?.reps.map((r) => [r.id, r.name]) ?? []), [heatmap.data]);
  const tolerance = Math.round((config.data?.similarity.similarity_tolerance ?? 0.1) * 100);
  const minDomains = config.data?.similarity.similarity_min_domains ?? 3;

  return (
    <Panel
      title="Rule-based similarity next to GDS node similarity"
      description={
        <>
          The rule (used for assignment) asks whether two reps win at a similar rate: within {tolerance} points in at least{" "}
          {minDomains} shared domains. GDS weighted Jaccard asks how much their domain footprints overlap, weighted by win rate.
          They measure different things, so disagreements are expected and useful for tuning.
        </>
      }
    >
      {compare.isLoading ? (
        <Loading label="Running GDS node similarity (the first run after a restart can take up to a minute)" />
      ) : (
        <QueryState query={compare} isEmpty={(rows) => rows.length === 0} empty={<EmptyState title="No similar pairs" />}>
          {(rows) => (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Pair</th>
                    <th className="text-right">Rule score</th>
                    <th>Matched domains (rule)</th>
                    <th className="text-right">GDS score</th>
                    <th>Reading</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <SimilarityRow key={`${r.rep_a}|${r.rep_b}`} row={r} names={names} />
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </QueryState>
      )}
    </Panel>
  );
}

function SimilarityRow({ row, names }: { row: SimilarityCompareRow; names: Map<string, string> }) {
  const reading =
    row.rule_score != null && row.gds_score != null
      ? "Both methods agree"
      : row.rule_score != null
        ? "Rule only"
        : "Same domains, different win rates";
  return (
    <tr>
      <td className="whitespace-nowrap">
        <Link to={`/reps/${row.rep_a}`} className="link">
          {names.get(row.rep_a) ?? row.rep_a}
        </Link>
        <span className="text-ink-faint"> and </span>
        <Link to={`/reps/${row.rep_b}`} className="link">
          {names.get(row.rep_b) ?? row.rep_b}
        </Link>
      </td>
      <td className="num text-right">{row.rule_score == null ? <span className="text-ink-faint">—</span> : formatDecimal(row.rule_score)}</td>
      <td>
        {row.rule_matched_domains ? (
          <div className="flex flex-wrap gap-1">
            {row.rule_matched_domains.map((d) => (
              <DomainChip key={d} domain={d} />
            ))}
          </div>
        ) : (
          <span className="text-xs text-ink-faint">Not similar under the rule</span>
        )}
      </td>
      <td className="num text-right">{row.gds_score == null ? <span className="text-ink-faint">—</span> : formatDecimal(row.gds_score, 4)}</td>
      <td className="text-xs text-ink-muted">{reading}</td>
    </tr>
  );
}
