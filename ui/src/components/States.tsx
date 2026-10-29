import type { ReactNode } from "react";

import { errorMessage } from "../api/client";

export function Loading({ label = "Loading", className = "" }: { label?: string; className?: string }) {
  return (
    <div className={`flex items-center gap-2 px-4 py-6 text-[13px] text-ink-muted ${className}`} role="status">
      <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-line-strong border-t-accent" />
      {label}…
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  return (
    <div className="m-4 rounded border border-lost/25 bg-lost-soft px-3 py-2.5 text-[13px] text-lost" role="alert">
      <div className="flex items-start justify-between gap-3">
        <span>{errorMessage(error)}</span>
        {onRetry && (
          <button type="button" className="shrink-0 font-medium underline underline-offset-2" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="px-4 py-8 text-center">
      <div className="text-[13px] font-medium text-ink">{title}</div>
      {children && <div className="mt-1 text-xs text-ink-muted">{children}</div>}
    </div>
  );
}

/** Renders loading / error / empty states for a react-query result, or `children` with the data. */
export function QueryState<T>({
  query,
  isEmpty,
  empty,
  children,
}: {
  query: { data: T | undefined; isLoading: boolean; error: unknown; refetch: () => unknown };
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  if (query.isLoading) return <Loading />;
  if (query.error) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data === undefined) return null;
  if (isEmpty?.(query.data)) return <>{empty ?? <EmptyState title="Nothing to show" />}</>;
  return <>{children(query.data)}</>;
}
