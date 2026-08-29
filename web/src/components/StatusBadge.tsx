import clsx from "clsx";

import { statusLabel } from "@/lib/format";
import type { SubmissionStatus } from "@/api/types";

const TONE: Record<SubmissionStatus, string> = {
  draft: "bg-slate-100 text-slate-700 border-slate-300",
  finalized: "bg-blue-50 text-blue-800 border-blue-200",
  in_review: "bg-amber-50 text-amber-800 border-amber-200",
  approved: "bg-green-50 text-green-800 border-green-200",
  rejected: "bg-red-50 text-red-800 border-red-200",
  correction_required: "bg-orange-50 text-orange-800 border-orange-200",
};

export function StatusBadge({ status }: { status: SubmissionStatus }) {
  return (
    <span
      className={clsx(
        "inline-block whitespace-nowrap rounded border px-1.5 py-0.5 text-xs",
        TONE[status] ?? TONE.draft,
      )}
    >
      {statusLabel(status)}
    </span>
  );
}
