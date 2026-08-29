/** Formatting shared by the submission views. */

const dateTime = new Intl.DateTimeFormat(undefined, {
  dateStyle: "medium",
  timeStyle: "medium",
});

export function formatTimestamp(iso: string | null): string {
  if (iso === null) return "—";
  const at = new Date(iso);
  return Number.isNaN(at.getTime()) ? iso : dateTime.format(at);
}

/** "12s ago" / "4m ago" — for how stale the view is, not for audit trails. */
export function formatAge(iso: string | number | null): string {
  if (iso === null) return "never";
  const at = typeof iso === "number" ? iso : new Date(iso).getTime();
  if (Number.isNaN(at)) return "unknown";
  const seconds = Math.max(0, Math.round((Date.now() - at) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  return `${Math.round(minutes / 60)}h ago`;
}

/** JSON, deliberately: quoted strings and a literal `null` are unambiguous. */
export function formatValue(value: unknown): string {
  if (value === undefined) return "—";
  try {
    return JSON.stringify(value) ?? "—";
  } catch {
    // JSON.stringify throws on exactly two things: a cycle, and a BigInt. A
    // BigInt is a value worth showing. A cycle is a structure, and rendering
    // it via String() would put "[object Object]" in a cell where every other
    // row holds an answer — say what it is instead of showing something that
    // reads like data.
    return typeof value === "bigint" ? `${value}n` : `(unrenderable ${typeof value})`;
  }
}

/** Enough of an id to recognise a row; the full id is on the detail page. */
export function shortId(id: string): string {
  return id.length <= 12 ? id : `${id.slice(0, 6)}…${id.slice(-4)}`;
}

const STATUS_LABELS: Record<string, string> = {
  draft: "draft",
  finalized: "finalized",
  in_review: "in review",
  approved: "approved",
  rejected: "rejected",
  correction_required: "correction required",
};

export function statusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}
