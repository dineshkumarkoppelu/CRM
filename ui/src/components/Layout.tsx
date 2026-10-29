import { useState, type ReactNode } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";

import { errorMessage } from "../api/client";
import { useHealth, useRecompute, useSeed } from "../api/hooks";
import { formatDate } from "../lib/format";
import { ConfirmDialog } from "./Overlay";

// 16px stroke icons, drawn for this app.
const ICONS: Record<string, ReactNode> = {
  dashboard: <path d="M2.5 2.5h4.5v6h-4.5zM9 2.5h4.5v3.5H9zM9 8h4.5v5.5H9zM2.5 10.5h4.5v3H2.5z" />,
  deals: <path d="M2.5 4h11M2.5 8h11M2.5 12h7" />,
  heatmap: <path d="M2.5 2.5h3.5v3.5H2.5zM6 2.5h3.5v3.5H6zM9.5 2.5H13v3.5H9.5zM2.5 6h3.5v3.5H2.5zM6 6h3.5v3.5H6zM9.5 6H13v3.5H9.5zM2.5 9.5h3.5V13H2.5zM6 9.5h3.5V13H6zM9.5 9.5H13V13H9.5z" />,
  graph: <path d="M4 4.5a1.5 1.5 0 1 0 0-.01M12 3.5a1.5 1.5 0 1 0 0-.01M8.5 12a1.5 1.5 0 1 0 0-.01M5.3 4.6l5.3-.9M4.7 5.8l3.2 5M11.4 4.9 9.2 10.6" />,
};

const NAV = [
  { to: "/", label: "Dashboard", icon: "dashboard", end: true },
  { to: "/deals", label: "Clients & Deals", icon: "deals", end: false },
  { to: "/heatmap", label: "Heatmap", icon: "heatmap", end: false },
  { to: "/graph", label: "Graph Explorer", icon: "graph", end: false },
];

function NavIcon({ name }: { name: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" aria-hidden>
      {ICONS[name]}
    </svg>
  );
}

function AdminMenu() {
  const [open, setOpen] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [notice, setNotice] = useState<{ kind: "ok" | "error"; text: string } | null>(null);
  const seed = useSeed();
  const recompute = useRecompute();

  const runSeed = () =>
    seed.mutate(undefined, {
      onSuccess: (r) => {
        setConfirm(false);
        setNotice({
          kind: "ok",
          text: `Demo data reset: ${r.counts.Deal} deals, ${r.counts.Client} clients, ${r.similar_pairs} similar pairs (${(r.duration_ms / 1000).toFixed(1)} s).`,
        });
      },
      onError: (e) => {
        setConfirm(false);
        setNotice({ kind: "error", text: errorMessage(e) });
      },
    });

  const runRecompute = () => {
    setOpen(false);
    recompute.mutate(undefined, {
      onSuccess: (r) =>
        setNotice({ kind: "ok", text: `Recomputed ${r.expertise_edges} expertise edges and ${r.similar_pairs} similar pairs.` }),
      onError: (e) => setNotice({ kind: "error", text: errorMessage(e) }),
    });
  };

  return (
    <div className="relative">
      <button type="button" className="btn btn-sm" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        Admin
        <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden>
          <path d="M2 3.5 5 6.5 8 3.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        </svg>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-30 mt-1 w-60 rounded-md border border-line bg-panel py-1 shadow-md">
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-[13px] hover:bg-canvas"
            onClick={() => {
              setOpen(false);
              setConfirm(true);
            }}
          >
            Reset demo data
            <span className="block text-xs text-ink-muted">Wipe and reload the synthetic dataset</span>
          </button>
          <button
            type="button"
            role="menuitem"
            className="block w-full px-3 py-2 text-left text-[13px] hover:bg-canvas disabled:opacity-50"
            onClick={runRecompute}
            disabled={recompute.isPending}
          >
            {recompute.isPending ? "Recomputing…" : "Recompute"}
            <span className="block text-xs text-ink-muted">Rebuild expertise and similarity now</span>
          </button>
        </div>
      )}
      <ConfirmDialog
        open={confirm}
        title="Reset demo data?"
        confirmLabel="Reset data"
        danger
        busy={seed.isPending}
        onConfirm={runSeed}
        onCancel={() => setConfirm(false)}
      >
        This deletes every sales person, client, deal and activity in the database and loads the
        synthetic dataset again. Deals and overrides created during the demo are lost.
      </ConfirmDialog>
      {notice && (
        <div
          role="status"
          className={`fixed right-4 bottom-4 z-50 flex max-w-md items-start gap-3 rounded-md border px-3.5 py-2.5 text-[13px] shadow-md ${
            notice.kind === "ok" ? "border-won/30 bg-panel text-ink" : "border-lost/30 bg-lost-soft text-lost"
          }`}
        >
          <span>{notice.text}</span>
          <button type="button" className="text-xs text-ink-muted hover:text-ink" onClick={() => setNotice(null)}>
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

export function Layout({ children }: { children: ReactNode }) {
  const health = useHealth();
  const { pathname } = useLocation();
  const degraded = health.data && health.data.status !== "ok";
  return (
    <div className="flex h-screen min-w-[1024px]">
      <aside className="flex w-56 shrink-0 flex-col bg-sidebar text-[#c3cad6]">
        <Link to="/" className="flex items-center gap-2.5 px-4 py-4">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          <span className="text-[13px] font-semibold tracking-tight text-white">CRM Graph Analytics</span>
        </Link>
        <nav className="mt-2 flex flex-col gap-0.5 px-2">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded px-2.5 py-1.5 text-[13px] ${
                  isActive || (item.to === "/deals" && pathname.startsWith("/clients"))
                    ? "bg-white/10 text-white"
                    : "hover:bg-white/5 hover:text-white"
                }`
              }
            >
              <NavIcon name={item.icon} />
              {item.label}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto px-4 py-4 text-[11px] leading-relaxed text-[#7d8697]">
          Neo4j {health.data?.neo4j.version ?? "—"} · GDS {health.data?.neo4j.gds_version ?? "—"}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-line bg-panel px-6">
          <div className="text-[13px] text-ink-muted">
            {health.data ? (
              <>
                Data as of <span className="font-medium text-ink">{formatDate(health.data.as_of_date)}</span>
              </>
            ) : health.error ? (
              <span className="text-lost">API unreachable</span>
            ) : null}
            {degraded && (
              <span className="ml-3 rounded-sm bg-warn-soft px-1.5 py-0.5 text-xs text-warn">
                {health.data?.neo4j.connected ? "Degraded: check plugins / schema" : "Database unreachable"}
              </span>
            )}
          </div>
          <AdminMenu />
        </header>
        <main className="flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="flex items-end justify-between gap-4 px-6 pt-5 pb-4">
      <div>
        <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
        {description && <p className="mt-0.5 text-[13px] text-ink-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Panel({
  title,
  description,
  actions,
  children,
  className = "",
  bodyClassName = "",
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {(title || actions) && (
        <div className="flex items-center justify-between gap-3 border-b border-line px-4 py-2.5">
          <div>
            {title && <h2 className="section-title">{title}</h2>}
            {description && <p className="text-xs text-ink-muted">{description}</p>}
          </div>
          {actions}
        </div>
      )}
      <div className={bodyClassName}>{children}</div>
    </section>
  );
}

export function Tabs<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
}) {
  return (
    <div role="tablist" className="inline-flex rounded border border-line-strong bg-panel p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="tab"
          aria-selected={value === o.value}
          className={`h-6 rounded-sm px-2.5 text-xs font-medium ${
            value === o.value ? "bg-accent-soft text-accent" : "text-ink-muted hover:text-ink"
          }`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
