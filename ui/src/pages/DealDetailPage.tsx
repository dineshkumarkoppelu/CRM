import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { errorMessage } from "../api/client";
import {
  useDeal,
  useHealth,
  useLogActivity,
  useMoveStage,
  useOverride,
  usePreview,
  useRecommendations,
  useRunAssignment,
  useSalesPeople,
} from "../api/hooks";
import type { ActivityType, DealDetail, Outcome, StageAction } from "../api/types";
import { AssignmentPanel } from "../components/AssignmentPanel";
import { DomainChip, StageLabel, StatusBadge } from "../components/Badges";
import { Panel } from "../components/Layout";
import { ClientLink, RepLink } from "../components/Links";
import { ConfirmDialog } from "../components/Overlay";
import { EmptyState, QueryState } from "../components/States";
import { STAGE_LABEL, STAGES } from "../lib/domains";
import { formatDate, formatINR, titleCase } from "../lib/format";

export function DealDetailPage() {
  const { id } = useParams();
  const deal = useDeal(id);
  return (
    <div className="px-6 pt-5 pb-8">
      <nav className="mb-2 text-xs text-ink-muted">
        <Link to="/deals" className="link">
          Deals
        </Link>{" "}
        / {id}
      </nav>
      <QueryState query={deal}>{(d) => <DealView deal={d} />}</QueryState>
    </div>
  );
}

function DealView({ deal }: { deal: DealDetail }) {
  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-lg font-semibold tracking-tight">{deal.title}</h1>
            <StatusBadge status={deal.status} />
            <StageLabel stage={deal.stage} />
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-ink-muted">
            <ClientLink id={deal.client_id} name={deal.client_name} />
            <DomainChip domain={deal.domain} />
            <span className="num font-medium text-ink">{formatINR(deal.value)}</span>
            <span>
              Owner <RepLink id={deal.owner_id} name={deal.owner_name} />
            </span>
            <span>{deal.closed_at ? `Closed ${formatDate(deal.closed_at)}` : `Expected close ${formatDate(deal.expected_close_date)}`}</span>
          </div>
        </div>
        {deal.status === "OPEN" && <StageActions deal={deal} />}
      </div>

      <Panel title="Stage history">
        <StageTimeline deal={deal} />
      </Panel>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-5">
        <div className="xl:col-span-3">
          <AssignmentSection deal={deal} />
        </div>
        <div className="xl:col-span-2">
          <ActivitiesSection deal={deal} />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- stage

function StageActions({ deal }: { deal: DealDetail }) {
  const move = useMoveStage();
  const [confirm, setConfirm] = useState<StageAction | null>(null);
  const index = STAGES.indexOf(deal.stage);
  const next = STAGES[index + 1];
  const run = (action: StageAction) => move.mutate({ dealId: deal.id, action }, { onSettled: () => setConfirm(null) });
  return (
    <div className="flex flex-col items-end gap-1.5">
      <div className="flex gap-2">
        {next ? (
          <button type="button" className="btn" disabled={move.isPending} onClick={() => run("ADVANCE")}>
            Advance to {STAGE_LABEL[next]}
          </button>
        ) : (
          <button type="button" className="btn btn-primary" disabled={move.isPending} onClick={() => setConfirm("WIN")}>
            Mark as won
          </button>
        )}
        <button type="button" className="btn text-lost" disabled={move.isPending} onClick={() => setConfirm("LOSE")}>
          Mark as lost
        </button>
      </div>
      {move.error && <p className="text-xs text-lost">{errorMessage(move.error)}</p>}
      <ConfirmDialog
        open={confirm !== null}
        title={confirm === "WIN" ? "Mark this deal as won?" : "Mark this deal as lost?"}
        confirmLabel={confirm === "WIN" ? "Mark as won" : "Mark as lost"}
        danger={confirm === "LOSE"}
        busy={move.isPending}
        onConfirm={() => confirm && run(confirm)}
        onCancel={() => setConfirm(null)}
      >
        Closing a deal is final: it cannot be moved again. The close date is recorded as today.
      </ConfirmDialog>
    </div>
  );
}

function StageTimeline({ deal }: { deal: DealDetail }) {
  const closing = deal.status === "WON" ? "Won" : deal.status === "LOST" ? "Lost" : "Closed";
  const steps = [
    { label: "Lead", date: deal.created_at },
    { label: "Qualified", date: deal.qualified_at },
    { label: "Proposal", date: deal.proposal_at },
    { label: "Negotiation", date: deal.negotiation_at },
    { label: closing, date: deal.closed_at, tone: deal.status },
  ];
  return (
    <ol className="grid grid-cols-5 px-4 py-4">
      {steps.map((step, i) => {
        const reached = Boolean(step.date);
        const dot =
          !reached ? "border-line-strong bg-panel" : step.tone === "LOST" ? "border-lost bg-lost" : step.tone === "WON" ? "border-won bg-won" : "border-accent bg-accent";
        return (
          <li key={step.label} className="relative">
            {i > 0 && <span className={`absolute top-[5px] right-1/2 left-[-50%] h-px ${reached ? "bg-accent/60" : "bg-line"}`} />}
            <div className="relative flex flex-col items-center text-center">
              <span className={`h-[11px] w-[11px] rounded-full border-2 ${dot}`} />
              <span className={`mt-1.5 text-[13px] ${reached ? "font-medium" : "text-ink-faint"}`}>{step.label}</span>
              <span className="num text-xs text-ink-muted">{reached ? formatDate(step.date) : "—"}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

// ---------------------------------------------------------------- assignment

function AssignmentSection({ deal }: { deal: DealDetail }) {
  const recommendations = useRecommendations(deal.id);
  const override = useOverride();
  const preview = usePreview();
  const run = useRunAssignment();
  const open = deal.status === "OPEN";

  return (
    <div className="space-y-4">
      <Panel
        title="Assignment"
        description="Ranking stored when the deal was assigned. The manager can hand it to another candidate."
        actions={
          open && (
            <div className="flex gap-2">
              {!deal.owner_id && (
                <button type="button" className="btn btn-sm btn-primary" disabled={run.isPending} onClick={() => run.mutate(deal.id)}>
                  {run.isPending ? "Assigning…" : "Run assignment"}
                </button>
              )}
              <button type="button" className="btn btn-sm" disabled={preview.isPending} onClick={() => preview.mutate(deal.id)}>
                {preview.isPending ? "Ranking…" : "Preview ranking"}
              </button>
            </div>
          )
        }
        bodyClassName="p-4"
      >
        <QueryState query={recommendations}>
          {(r) =>
            r.candidates.length === 0 && r.assignment_status !== "UNASSIGNED" ? (
              <EmptyState title={r.message}>This deal was not routed by the engine, so no ranking is stored.</EmptyState>
            ) : (
              <AssignmentPanel
                result={r}
                onOverride={open ? (repId) => override.mutate({ dealId: deal.id, repId }) : undefined}
                overridingId={override.isPending ? override.variables?.repId : null}
              />
            )
          }
        </QueryState>
        {(override.error || run.error) && <p className="mt-3 text-[13px] text-lost">{errorMessage(override.error ?? run.error)}</p>}
      </Panel>

      {(preview.data || preview.error) && (
        <Panel
          title="Ranking preview"
          description="Computed from current data. Nothing is saved."
          actions={
            <button type="button" className="btn btn-ghost btn-sm" onClick={() => preview.reset()}>
              Hide
            </button>
          }
          bodyClassName="p-4"
        >
          {preview.error ? <p className="text-[13px] text-lost">{errorMessage(preview.error)}</p> : preview.data && <AssignmentPanel result={preview.data} preview />}
        </Panel>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- activities

const ACTIVITY_TYPES: ActivityType[] = ["CALL", "EMAIL", "MEETING", "DEMO"];
const OUTCOMES: Outcome[] = ["POSITIVE", "NEUTRAL", "NEGATIVE"];
const OUTCOME_STYLE: Record<Outcome, string> = { POSITIVE: "text-won", NEUTRAL: "text-ink-muted", NEGATIVE: "text-lost" };

function ActivitiesSection({ deal }: { deal: DealDetail }) {
  return (
    <Panel title="Activities" description={`${deal.activities.length} logged, newest first.`}>
      <ActivityForm key={deal.id} deal={deal} />
      {deal.activities.length === 0 ? (
        <EmptyState title="No activities yet" />
      ) : (
        <ul className="max-h-[420px] divide-y divide-line overflow-y-auto">
          {deal.activities.map((a) => (
            <li key={a.id} className="flex items-center justify-between gap-3 px-4 py-2 text-[13px]">
              <div>
                <span className="font-medium">{titleCase(a.type)}</span>
                <span className="text-ink-muted"> by </span>
                <RepLink id={a.sales_person_id} name={a.sales_person_name} />
              </div>
              <div className="flex items-center gap-3 text-xs">
                <span className={OUTCOME_STYLE[a.outcome]}>{titleCase(a.outcome)}</span>
                <span className="num text-ink-muted">{formatDate(a.date)}</span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}

function ActivityForm({ deal }: { deal: DealDetail }) {
  const health = useHealth();
  const reps = useSalesPeople();
  const log = useLogActivity();
  const today = health.data?.as_of_date ?? "";
  const [type, setType] = useState<ActivityType>("CALL");
  const [outcome, setOutcome] = useState<Outcome>("POSITIVE");
  const [date, setDate] = useState("");
  const [rep, setRep] = useState(deal.owner_id ?? "");

  const submit = (event: FormEvent) => {
    event.preventDefault();
    log.mutate(
      { deal_id: deal.id, sales_person_id: rep, type, outcome, date: date || undefined },
      { onSuccess: () => setDate("") },
    );
  };

  return (
    <form onSubmit={submit} className="border-b border-line bg-canvas/50 px-4 py-3">
      <div className="grid grid-cols-2 gap-2">
        <select className="input" aria-label="Activity type" value={type} onChange={(e) => setType(e.target.value as ActivityType)}>
          {ACTIVITY_TYPES.map((t) => (
            <option key={t} value={t}>
              {titleCase(t)}
            </option>
          ))}
        </select>
        <select className="input" aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
          {OUTCOMES.map((o) => (
            <option key={o} value={o}>
              {titleCase(o)}
            </option>
          ))}
        </select>
        <select className="input" aria-label="Logged by" required value={rep} onChange={(e) => setRep(e.target.value)}>
          <option value="">Logged by…</option>
          {reps.data?.items.map((r) => (
            <option key={r.id} value={r.id}>
              {r.name}
            </option>
          ))}
        </select>
        <input
          className="input"
          type="date"
          aria-label="Date (defaults to today)"
          title="Leave empty for today"
          min={deal.created_at}
          max={deal.closed_at ?? today}
          value={date}
          onChange={(e) => setDate(e.target.value)}
        />
      </div>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-xs text-lost">{log.error ? errorMessage(log.error) : ""}</span>
        <button type="submit" className="btn btn-sm btn-primary" disabled={log.isPending || !rep}>
          {log.isPending ? "Saving…" : "Log activity"}
        </button>
      </div>
    </form>
  );
}
