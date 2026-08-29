/** One submission: the folded current state, and the log it was folded from. */

import type { ReactNode } from "react";
import { Link, getRouteApi } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { REFRESH_INTERVAL_MS, submissionQuery } from "@/api/queries";
import type { SubmissionOpView } from "@/api/types";
import { RefreshControls, useAutoRefresh } from "@/components/RefreshControls";
import { StatusBadge } from "@/components/StatusBadge";
import { formatTimestamp, formatValue } from "@/lib/format";
import { Td, Th } from "@/components/Table";

const route = getRouteApi("/submissions/$submissionId");

export function SubmissionPage() {
  const { submissionId } = route.useParams();
  const autoRefresh = useAutoRefresh((state) => state.enabled);

  const submission = useQuery({
    ...submissionQuery(submissionId),
    refetchInterval: autoRefresh ? REFRESH_INTERVAL_MS : false,
  });

  if (submission.isPending) {
    return <p className="text-slate-500">Loading…</p>;
  }
  if (submission.isError) {
    return (
      <div>
        <BackLink />
        <p className="mt-4 text-red-600">
          Could not load {submissionId}: {String(submission.error)}
        </p>
      </div>
    );
  }

  const detail = submission.data;
  const stateEntries = Object.entries(detail.state?.data ?? {}).sort(
    ([a], [b]) => a.localeCompare(b),
  );

  return (
    <section>
      <BackLink />

      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-mono text-xl font-semibold">{detail.id}</h1>
          <p className="mt-1 text-sm text-slate-600">
            {detail.formTitle}{" "}
            <span className="text-slate-500">
              ({detail.formId} v{detail.formVersion})
            </span>
          </p>
        </div>
        <RefreshControls
          isFetching={submission.isFetching}
          updatedAt={submission.dataUpdatedAt}
          onRefresh={() => void submission.refetch()}
        />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
        <Fact label="Status">
          <StatusBadge status={detail.status} />
        </Fact>
        <Fact label="Origin device">
          <span className="font-mono text-xs">
            {detail.originDeviceId ?? "—"}
          </span>
        </Fact>
        <Fact label="Ops">{detail.opCount}</Fact>
        <Fact label="Received">{formatTimestamp(detail.receivedAt)}</Fact>
        <Fact label="Started">{formatTimestamp(detail.startedAt)}</Fact>
        <Fact label="Finalized">{formatTimestamp(detail.finalizedAt)}</Fact>
        <Fact label="Created by">{detail.createdBy ?? "—"}</Fact>
        <Fact label="Project">
          <span className="font-mono text-xs">{detail.projectId}</span>
        </Fact>
      </dl>

      <h2 className="mt-8 text-lg font-semibold">Current state</h2>
      <p className="text-sm text-slate-600">
        The server&apos;s fold of the log below, last computed{" "}
        {formatTimestamp(detail.state?.computedAt ?? null)}.
      </p>
      {stateEntries.length === 0 ? (
        <p className="mt-3 text-slate-500">No values yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-slate-600">
                <Th>Path</Th>
                <Th>Value</Th>
              </tr>
            </thead>
            <tbody>
              {stateEntries.map(([path, value]) => (
                <tr key={path} className="border-b border-slate-100">
                  <Td className="font-mono text-xs">{path}</Td>
                  <Td className="font-mono text-xs">{formatValue(value)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mt-8 text-lg font-semibold">Op log</h2>
      <p className="text-sm text-slate-600">
        In (counter, deviceId) order — the order the fold replays in. Wall
        clocks are diagnostic and never order anything.
      </p>
      {detail.opsTruncated && (
        <p className="mt-2 text-sm text-amber-700">
          Showing the first {detail.ops.length} of {detail.opCount} ops.
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[56rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-slate-600">
              <Th className="text-end">#</Th>
              <Th className="text-end">Counter</Th>
              <Th>Device</Th>
              <Th>Kind</Th>
              <Th>Path</Th>
              <Th>Value</Th>
              <Th>Wall clock</Th>
              <Th>Received</Th>
            </tr>
          </thead>
          <tbody>
            {detail.ops.map((op, index) => (
              <tr key={op.id} className="border-b border-slate-100">
                <Td className="text-end tabular-nums text-slate-500">
                  {index + 1}
                </Td>
                <Td className="text-end tabular-nums">{op.counter}</Td>
                <Td className="font-mono text-xs">{op.deviceId}</Td>
                <Td>
                  <code>{op.kind}</code>
                </Td>
                <Td className="font-mono text-xs">{op.path ?? "—"}</Td>
                <Td className="font-mono text-xs">
                  <OpValue op={op} />
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {formatTimestamp(op.wallClock)}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {formatTimestamp(op.receivedAt)}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail.ops.length === 0 && (
        <p className="py-6 text-slate-500">This submission has no ops.</p>
      )}
    </section>
  );
}

function OpValue({ op }: { op: SubmissionOpView }) {
  if (op.encrypted) {
    // The console holds no keys, by design (encryption envelope §3).
    return <span className="text-slate-500">encrypted</span>;
  }
  return <>{formatValue(op.value)}</>;
}

function BackLink() {
  return (
    <Link
      to="/submissions"
      className="text-sm text-blue-700 hover:underline"
    >
      ← All submissions
    </Link>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
