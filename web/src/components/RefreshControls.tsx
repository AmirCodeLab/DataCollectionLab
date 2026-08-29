/** Auto-refresh toggle plus a manual refresh, shared by both views. */

import { useEffect, useState } from "react";

import { useAutoRefresh } from "@/lib/autoRefresh";
import { formatAge } from "@/lib/format";

interface Props {
  isFetching: boolean;
  /** react-query's dataUpdatedAt: 0 until the first response arrives. */
  updatedAt: number;
  onRefresh: () => void;
}

export function RefreshControls({ isFetching, updatedAt, onRefresh }: Props) {
  const { enabled, setEnabled } = useAutoRefresh();
  const age = useTicking(updatedAt);

  return (
    <div className="flex items-center gap-3 text-sm text-slate-600">
      <span aria-live="polite">
        {isFetching ? "refreshing…" : `updated ${age}`}
      </span>
      <label className="flex items-center gap-1.5">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        auto
      </label>
      <button
        type="button"
        onClick={onRefresh}
        className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100"
      >
        Refresh
      </button>
    </div>
  );
}

/** Re-renders once a second so "updated 4s ago" stays true with auto off. */
function useTicking(updatedAt: number): string {
  const [, setTick] = useState(0);
  useEffect(() => {
    const timer = window.setInterval(() => setTick((t) => t + 1), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return updatedAt === 0 ? "never" : formatAge(updatedAt);
}
