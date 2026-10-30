// Live updates: the API pushes a Server-Sent Event whenever data changed in Neo4j (an edit made
// anywhere - this UI, the Postgres API, a script). Each event refetches what is on screen.
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export type LiveState = "connecting" | "live" | "offline";

const REFETCH_DELAY_MS = 250; // a burst of events becomes one refetch

export function useLiveUpdates(): LiveState {
  const queryClient = useQueryClient();
  const [state, setState] = useState<LiveState>(typeof EventSource === "undefined" ? "offline" : "connecting");

  useEffect(() => {
    if (typeof EventSource === "undefined") return;
    let timer: number | undefined;
    const refresh = () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void queryClient.invalidateQueries(), REFETCH_DELAY_MS);
    };

    const source = new EventSource("/api/events");
    source.addEventListener("hello", () => {
      setState("live");
      refresh(); // also catches up on anything missed while the connection was down
    });
    source.addEventListener("change", refresh);
    // EventSource reconnects by itself; until it does, say so.
    source.onerror = () => setState(source.readyState === EventSource.CLOSED ? "offline" : "connecting");

    return () => {
      window.clearTimeout(timer);
      source.close();
    };
  }, [queryClient]);

  return state;
}
