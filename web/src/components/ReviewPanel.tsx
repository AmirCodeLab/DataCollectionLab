/** What the rules said about a submission, and the decision a reviewer makes.
 *
 * Three things here are decisions rather than layout.
 *
 * **A rule that could not be evaluated is not a rule that passed.** The server
 * holds ciphertext and no key for an encrypted project, so some rules never
 * ran. They are a separate list with their own sentence, never folded in with
 * the violations and never counted as part of "how much is wrong" — because a
 * reviewer who reads an empty flag list as a clean bill is the failure that
 * turns a quality feature into a quality risk (item 6, D3).
 *
 * **Nothing here says "no flags" unless the rules actually ran.** A submission
 * with no rules at all says so in those words.
 *
 * **Sending work back needs a reason, and the control says so before it is
 * used.** The server refuses without one; the screen should not let somebody
 * find that out by being refused.
 */

import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";

import { reviewSubmission, submissionQualityQuery } from "@/api/queries";
import type { Decision, FlagView, SubmissionQualityResponse } from "@/api/types";

/** The decisions, in the order a reviewer meets them. */
const DECISIONS: { value: Decision; label: string; returnsWork: boolean }[] = [
  { value: "approved", label: "Approve", returnsWork: false },
  { value: "correction_required", label: "Send back for correction", returnsWork: true },
  { value: "rejected", label: "Reject", returnsWork: true },
  { value: "comment", label: "Comment only", returnsWork: false },
];

export function ReviewPanel({
  submissionId,
  quality,
  canReview,
  ruleCount,
}: {
  submissionId: string;
  quality: SubmissionQualityResponse;
  canReview: boolean;
  ruleCount: number | null;
}) {
  const client = useQueryClient();
  const [decision, setDecision] = useState<Decision>("approved");
  const [comment, setComment] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);

  const returnsWork =
    DECISIONS.find((d) => d.value === decision)?.returnsWork ?? false;

  const decide = useMutation({
    mutationFn: () =>
      reviewSubmission(submissionId, { decision, comment: comment || null }),
    onSuccess: () => {
      setComment("");
      setRefusal(null);
      void client.invalidateQueries({ queryKey: ["submission", submissionId] });
      void client.invalidateQueries({
        queryKey: submissionQualityQuery(submissionId).queryKey,
      });
      void client.invalidateQueries({ queryKey: ["submissions"] });
    },
    onError: (error: unknown) => {
      // The server's sentence, not one invented here: it knows which of the
      // four refusals this is and says what to do about it.
      const detail = (error as { detail?: { message?: string } })?.detail;
      setRefusal(detail?.message ?? String(error));
    },
  });

  return (
    <section className="mt-8">
      <h2 className="text-lg font-medium">Quality and review</h2>

      <Checked quality={quality} ruleCount={ruleCount} />

      {quality.flags.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2">
          {quality.flags.map((flag) => (
            <li
              key={flag.id}
              className="rounded border border-amber-300 bg-amber-50 p-3 text-sm"
            >
              <Flag flag={flag} />
            </li>
          ))}
        </ul>
      )}

      {quality.unevaluated.length > 0 && (
        <div className="mt-3 rounded border border-slate-300 bg-slate-50 p-3">
          <p className="text-sm font-medium">
            {quality.unevaluated.length === 1
              ? "1 rule could not be checked"
              : `${quality.unevaluated.length} rules could not be checked`}
          </p>
          <p className="mt-1 text-sm text-slate-600">
            These did not pass and did not fail. Nothing here has been checked.
          </p>
          <ul className="mt-2 flex flex-col gap-1 text-sm">
            {quality.unevaluated.map((flag) => (
              <li key={flag.id}>
                <span className="font-medium">{flag.ruleName ?? "A rule"}</span>
                {" — "}
                {reason(flag)}
              </li>
            ))}
          </ul>
        </div>
      )}

      {canReview ? (
        <div className="mt-4 rounded border border-slate-200 p-3">
          <label className="block text-sm">
            <span className="font-medium">Decision</span>
            <select
              className="mt-1 block w-full max-w-sm rounded border border-slate-300 p-2"
              value={decision}
              onChange={(event) => setDecision(event.target.value as Decision)}
            >
              {DECISIONS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="mt-3 block text-sm">
            <span className="font-medium">
              {returnsWork ? "What needs correcting" : "Comment"}
            </span>
            {returnsWork && (
              <span className="mt-1 block text-slate-600">
                Required. This is what the enumerator reads on the handset
                before they open the form again — without it the visit is
                repeated rather than corrected.
              </span>
            )}
            <textarea
              className="mt-1 block w-full rounded border border-slate-300 p-2"
              rows={3}
              value={comment}
              onChange={(event) => setComment(event.target.value)}
            />
          </label>
          <button
            type="button"
            className="mt-3 rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:bg-slate-400"
            disabled={decide.isPending || (returnsWork && comment.trim() === "")}
            onClick={() => decide.mutate()}
          >
            {decide.isPending ? "Recording…" : "Record decision"}
          </button>
          {refusal && (
            <p role="alert" className="mt-2 text-sm text-red-700">
              {refusal}
            </p>
          )}
        </div>
      ) : (
        <p className="mt-4 text-sm text-slate-600">
          You can see this submission but not decide on it. Reviewing needs
          submission.review.
        </p>
      )}

      {quality.reviews.length > 0 && (
        <div className="mt-6">
          <h3 className="text-sm font-medium">Decisions</h3>
          <ul className="mt-2 flex flex-col gap-2 text-sm">
            {quality.reviews.map((entry) => (
              <li key={entry.id} className="border-l-2 border-slate-200 pl-3">
                <div>
                  <span className="font-medium">{label(entry.decision)}</span>
                  {" by "}
                  {entry.reviewer ?? "somebody you cannot see"}
                  {" · "}
                  <span className="text-slate-500">
                    {entry.createdAt.slice(0, 16).replace("T", " ")}
                  </span>
                </div>
                {entry.comment && <div className="text-slate-700">{entry.comment}</div>}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

/** The sentence above everything, and the one that must never overstate. */
function Checked({
  quality,
  ruleCount,
}: {
  quality: SubmissionQualityResponse;
  ruleCount: number | null;
}) {
  if (ruleCount === 0) {
    return (
      <p className="mt-1 text-sm text-slate-600">
        This project has no quality rules, so nothing has been checked.
      </p>
    );
  }
  if (quality.flags.length === 0 && quality.unevaluated.length === 0) {
    return (
      <p className="mt-1 text-sm text-slate-600">
        Every rule ran and none of them found anything.
      </p>
    );
  }
  if (quality.flags.length === 0) {
    return (
      <p className="mt-1 text-sm text-slate-600">
        Nothing was flagged — but see below: not every rule could be checked.
      </p>
    );
  }
  return (
    <p className="mt-1 text-sm text-slate-600">
      {quality.flags.length === 1 ? "1 rule flagged this" : `${quality.flags.length} rules flagged this`}
      {quality.unevaluated.length > 0 && ", and others could not be checked"}.
    </p>
  );
}

function Flag({ flag }: { flag: FlagView }) {
  return (
    <>
      <div className="font-medium">{flag.ruleName ?? "A rule that no longer exists"}</div>
      <div className="text-slate-700">
        {flag.severity}
        {flag.path && <> · {flag.path}</>}
      </div>
    </>
  );
}

/** Why a rule could not run, in words rather than a code. */
function reason(flag: FlagView): string {
  const detail = flag.detail as { reason?: string; paths?: string[]; message?: string };
  if (detail.reason === "encrypted") {
    return `the answer is encrypted and this server holds no key (${(detail.paths ?? []).join(", ")})`;
  }
  if (detail.reason === "unknown_path") {
    return `it asks about ${(detail.paths ?? []).join(", ")}, which this form does not have`;
  }
  if (detail.reason === "invalid") {
    return detail.message ?? "the rule could not be evaluated";
  }
  return "it could not be evaluated";
}

function label(decision: Decision): string {
  switch (decision) {
    case "approved":
      return "Approved";
    case "rejected":
      return "Rejected";
    case "correction_required":
      return "Sent back for correction";
    default:
      return "Comment";
  }
}
