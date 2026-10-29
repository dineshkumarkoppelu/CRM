import { Link } from "react-router-dom";

// Links used inside clickable table rows stop the click from also triggering the row.

export function RepLink({ id, name }: { id: string | null | undefined; name: string | null | undefined }) {
  if (!id) return <span className="text-ink-faint">Unassigned</span>;
  return (
    <Link to={`/reps/${id}`} className="link" onClick={(e) => e.stopPropagation()}>
      {name ?? id}
    </Link>
  );
}

export function DealLink({ id, children }: { id: string; children?: React.ReactNode }) {
  return (
    <Link to={`/deals/${id}`} className="link" onClick={(e) => e.stopPropagation()}>
      {children ?? id}
    </Link>
  );
}

export function ClientLink({ id, name }: { id: string; name: string }) {
  return (
    <Link to={`/clients/${id}`} className="link" onClick={(e) => e.stopPropagation()}>
      {name}
    </Link>
  );
}
