import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type LinkObject, type NodeObject } from "react-force-graph-2d";
import { Link, useSearchParams } from "react-router-dom";

import { useSalesPeople, useSubgraph } from "../api/hooks";
import type { DealStatus, GraphLinkType, GraphNodeType } from "../api/types";
import { PageHeader } from "../components/Layout";
import { EmptyState, ErrorState, Loading } from "../components/States";
import { ACCENT, domainColor, STATUS_COLOR } from "../lib/domains";
import { formatDate, formatINR, formatPct } from "../lib/format";
import { useElementSize } from "../lib/useElementSize";

interface NodeData {
  id: string;
  label: string;
  type: GraphNodeType;
  props: Record<string, unknown>;
}
interface LinkData {
  type: GraphLinkType;
  props: Record<string, unknown>;
}
type GNode = NodeObject<NodeData>;
type GLink = LinkObject<NodeData, LinkData>;

const CLIENT_COLOR = "#8a93a3";
const PEER_COLOR = "#10857a";

const LINK_COLOR: Record<GraphLinkType, string> = {
  OWNS: "rgba(68, 96, 127, 0.35)",
  FOR_CLIENT: "rgba(138, 147, 163, 0.35)",
  IN_DOMAIN: "rgba(138, 147, 163, 0.25)",
  EXPERTISE_IN: "rgba(31, 79, 153, 0.7)",
  SIMILAR_TO: PEER_COLOR,
};

function nodeColor(node: NodeData, focusId: string): string {
  switch (node.type) {
    case "SalesPerson":
      return node.id === focusId ? ACCENT : PEER_COLOR;
    case "Domain":
      return domainColor(node.id);
    case "Client":
      return CLIENT_COLOR;
    case "Deal":
      return STATUS_COLOR[(node.props.status as DealStatus) ?? "OPEN"];
  }
}

function nodeRadius(node: NodeData, focusId: string): number {
  if (node.type === "SalesPerson") return node.id === focusId ? 9 : 7;
  if (node.type === "Domain") return 7;
  if (node.type === "Client") return 3.5;
  return 3;
}

export function GraphExplorerPage() {
  const [params, setParams] = useSearchParams();
  const repId = params.get("rep") ?? "SP-002";
  const includePeers = params.get("peers") !== "0";
  const status = (params.get("status") || undefined) as DealStatus | undefined;
  const reps = useSalesPeople();
  const subgraph = useSubgraph(repId, includePeers, status);
  const [selected, setSelected] = useState<NodeData | null>(null);

  const setParam = (key: string, value: string | null) => {
    const next = new URLSearchParams(params);
    if (value === null) next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
    setSelected(null);
  };

  return (
    <div className="flex h-full flex-col">
      <PageHeader
        title="Graph explorer"
        description="A sales person's deals, the clients and domains behind them, their expertise and their similar peers."
        actions={
          <>
            <label className="flex items-center gap-2 text-[13px]">
              <span className="text-ink-muted">Sales person</span>
              <select className="input w-48" value={repId} onChange={(e) => setParam("rep", e.target.value)}>
                {reps.data?.items.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-2 text-[13px]">
              <span className="text-ink-muted">Deals</span>
              <select className="input w-28" value={status ?? ""} onChange={(e) => setParam("status", e.target.value || null)}>
                <option value="">All</option>
                <option value="OPEN">Open</option>
                <option value="WON">Won</option>
                <option value="LOST">Lost</option>
              </select>
            </label>
            <label className="flex items-center gap-1.5 text-[13px]">
              <input type="checkbox" checked={includePeers} onChange={(e) => setParam("peers", e.target.checked ? null : "0")} />
              Similar peers
            </label>
          </>
        }
      />
      <div className="flex min-h-0 flex-1 gap-4 px-6 pb-6">
        <div className="panel relative min-h-[480px] flex-1 overflow-hidden">
          {subgraph.isLoading ? (
            <Loading label="Loading graph" />
          ) : subgraph.error ? (
            <ErrorState error={subgraph.error} onRetry={() => void subgraph.refetch()} />
          ) : subgraph.data && subgraph.data.nodes.length > 0 ? (
            <GraphCanvas data={subgraph.data} focusId={repId} onSelect={setSelected} selectedId={selected?.id} />
          ) : (
            <EmptyState title="Nothing to draw" />
          )}
          <Legend />
        </div>
        <aside className="panel w-72 shrink-0 overflow-y-auto">
          <NodeDetails node={selected} />
        </aside>
      </div>
    </div>
  );
}

function GraphCanvas({
  data,
  focusId,
  selectedId,
  onSelect,
}: {
  data: { nodes: NodeData[]; links: { source: string; target: string; type: GraphLinkType; props: Record<string, unknown> }[] };
  focusId: string;
  selectedId?: string;
  onSelect: (node: NodeData | null) => void;
}) {
  const container = useRef<HTMLDivElement>(null);
  const { width, height } = useElementSize(container);
  const graphRef = useRef<ForceGraphMethods<GNode, GLink> | undefined>(undefined);
  // Zoom to fit once per dataset, when the layout first settles.
  const fittedFor = useRef<object | null>(null);

  // force-graph mutates the objects it is given, so hand it copies.
  const graphData = useMemo(
    () => ({
      nodes: data.nodes.map((n) => ({ ...n })) as GNode[],
      links: data.links.map((l) => ({ ...l })) as GLink[],
    }),
    [data],
  );

  // Spread the layout out: stronger repulsion, longer links for the structural edges.
  useEffect(() => {
    const graph = graphRef.current;
    if (!graph) return;
    graph.d3Force("charge")?.strength(-140);
    graph
      .d3Force("link")
      ?.distance((l: GLink) => (l.type === "SIMILAR_TO" ? 160 : l.type === "EXPERTISE_IN" ? 110 : l.type === "OWNS" ? 70 : 35));
    graph.d3ReheatSimulation();
    // Fit early as well as when the layout settles, so the graph fills the canvas quickly.
    const timer = window.setTimeout(() => graphRef.current?.zoomToFit(400, 48), 900);
    return () => window.clearTimeout(timer);
  }, [graphData, width, height]);

  const drawNode = useCallback(
    (node: GNode, ctx: CanvasRenderingContext2D, scale: number) => {
      const r = nodeRadius(node, focusId);
      const x = node.x ?? 0;
      const y = node.y ?? 0;
      ctx.beginPath();
      if (node.type === "Domain") {
        ctx.rect(x - r, y - r, r * 2, r * 2);
      } else {
        ctx.arc(x, y, r, 0, 2 * Math.PI);
      }
      ctx.fillStyle = nodeColor(node, focusId);
      ctx.fill();
      if (node.id === selectedId) {
        ctx.lineWidth = 2 / scale;
        ctx.strokeStyle = "#1c2330";
        ctx.stroke();
      }
      const showLabel =
        node.type === "SalesPerson" || node.type === "Domain" || (node.type === "Client" && scale > 2.2) || (node.type === "Deal" && scale > 3.5);
      if (showLabel) {
        const size = (node.type === "SalesPerson" ? 12 : node.type === "Domain" ? 11 : 9) / scale;
        ctx.font = `${node.type === "SalesPerson" ? 600 : 400} ${size}px Inter, "Segoe UI", sans-serif`;
        ctx.textAlign = "center";
        ctx.textBaseline = "top";
        ctx.fillStyle = "#1c2330";
        ctx.fillText(node.type === "Deal" ? node.id : node.label, x, y + r + 2 / scale);
      }
    },
    [focusId, selectedId],
  );

  const paintArea = useCallback(
    (node: GNode, color: string, ctx: CanvasRenderingContext2D) => {
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.arc(node.x ?? 0, node.y ?? 0, nodeRadius(node, focusId) + 2, 0, 2 * Math.PI);
      ctx.fill();
    },
    [focusId],
  );

  const drawLinkLabel = useCallback((link: GLink, ctx: CanvasRenderingContext2D, scale: number) => {
    if (link.type !== "SIMILAR_TO") return;
    const s = link.source as GNode;
    const t = link.target as GNode;
    if (typeof s !== "object" || typeof t !== "object") return;
    const x = ((s.x ?? 0) + (t.x ?? 0)) / 2;
    const y = ((s.y ?? 0) + (t.y ?? 0)) / 2;
    const text = `similar ${Number(link.props.score).toFixed(2)}`;
    ctx.font = `500 ${10 / scale}px Inter, "Segoe UI", sans-serif`;
    const w = ctx.measureText(text).width + 6 / scale;
    ctx.fillStyle = "rgba(255,255,255,0.92)";
    ctx.fillRect(x - w / 2, y - 7 / scale, w, 14 / scale);
    ctx.fillStyle = PEER_COLOR;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, x, y);
  }, []);

  return (
    <div ref={container} className="absolute inset-0">
      {width > 0 && height > 0 && (
        <ForceGraph2D<NodeData, LinkData>
          ref={graphRef}
          width={width}
          height={height}
          graphData={graphData}
          backgroundColor="#ffffff"
          nodeId="id"
          nodeLabel={(n) => `${n.type}: ${n.label}`}
          nodeCanvasObject={drawNode}
          nodePointerAreaPaint={paintArea}
          linkColor={(l) => LINK_COLOR[l.type]}
          linkWidth={(l) => (l.type === "SIMILAR_TO" ? 2 : l.type === "EXPERTISE_IN" ? 1.5 : 0.7)}
          linkLineDash={(l) => (l.type === "SIMILAR_TO" ? [5, 3] : null)}
          linkLabel={(l) =>
            l.type === "EXPERTISE_IN"
              ? `EXPERTISE_IN · ${formatPct(l.props.win_rate as number)} (${l.props.won}/${l.props.handled})`
              : l.type === "SIMILAR_TO"
                ? `SIMILAR_TO · score ${Number(l.props.score).toFixed(2)}`
                : l.type
          }
          linkCanvasObjectMode={(l) => (l.type === "SIMILAR_TO" ? "after" : undefined)}
          linkCanvasObject={drawLinkLabel}
          cooldownTicks={150}
          d3VelocityDecay={0.3}
          onEngineStop={() => {
            if (fittedFor.current !== graphData) {
              fittedFor.current = graphData;
              graphRef.current?.zoomToFit(400, 48);
            }
          }}
          onNodeClick={(n) => onSelect(n)}
          onBackgroundClick={() => onSelect(null)}
        />
      )}
    </div>
  );
}

function Legend() {
  const items: [string, string, "circle" | "square" | "dash"][] = [
    ["Selected sales person", ACCENT, "circle"],
    ["Similar peer", PEER_COLOR, "circle"],
    ["Domain", domainColor("AI"), "square"],
    ["Client", CLIENT_COLOR, "circle"],
    ["Open deal", STATUS_COLOR.OPEN, "circle"],
    ["Won deal", STATUS_COLOR.WON, "circle"],
    ["Lost deal", STATUS_COLOR.LOST, "circle"],
    ["Similar to (dashed)", PEER_COLOR, "dash"],
  ];
  return (
    <div className="pointer-events-none absolute bottom-3 left-3 rounded border border-line bg-panel/95 px-3 py-2 text-[11px] text-ink-muted">
      {items.map(([label, color, shape]) => (
        <div key={label} className="flex items-center gap-2 leading-5">
          {shape === "dash" ? (
            <span className="w-3 border-t-2 border-dashed" style={{ borderColor: color }} />
          ) : (
            <span className={`h-2.5 w-2.5 ${shape === "circle" ? "rounded-full" : "rounded-[2px]"}`} style={{ backgroundColor: color }} />
          )}
          {label}
        </div>
      ))}
      <div className="mt-1 border-t border-line pt-1">Domains use their own colour. Scroll to zoom, drag to move.</div>
    </div>
  );
}

const PAGE_FOR: Record<GraphNodeType, ((id: string) => string) | null> = {
  SalesPerson: (id) => `/reps/${id}`,
  Deal: (id) => `/deals/${id}`,
  Client: (id) => `/clients/${id}`,
  Domain: null,
};

function formatProp(key: string, value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (key === "value") return formatINR(Number(value));
  if (key.endsWith("_at") || key.endsWith("_date")) return formatDate(String(value));
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

function NodeDetails({ node }: { node: NodeData | null }) {
  if (!node) {
    return (
      <div className="px-4 py-4 text-[13px] text-ink-muted">
        Click a node to see its details. Hover a line to see the relationship.
      </div>
    );
  }
  const page = PAGE_FOR[node.type];
  const props = Object.entries(node.props).filter(([key]) => key !== "peer");
  return (
    <div>
      <div className="border-b border-line px-4 py-3">
        <div className="text-xs text-ink-muted">{node.type === "SalesPerson" ? "Sales person" : node.type}</div>
        <div className="mt-0.5 text-[14px] font-semibold">{node.label}</div>
        <div className="text-xs text-ink-faint">{node.id}</div>
      </div>
      {props.length > 0 && (
        <dl className="divide-y divide-line text-[13px]">
          {props.map(([key, value]) => (
            <div key={key} className="flex justify-between gap-3 px-4 py-1.5">
              <dt className="text-ink-muted">{key.replace(/_/g, " ")}</dt>
              <dd className="num text-right">{formatProp(key, value)}</dd>
            </div>
          ))}
        </dl>
      )}
      {page && (
        <div className="px-4 py-3">
          <Link to={page(node.id)} className="btn btn-sm">
            Open {node.type === "SalesPerson" ? "profile" : node.type.toLowerCase()}
          </Link>
        </div>
      )}
    </div>
  );
}
