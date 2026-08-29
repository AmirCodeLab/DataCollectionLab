/** The submission list: what arrived, from which device, and how much of it. */

import { Link, getRouteApi, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { REFRESH_INTERVAL_MS, formListQuery, submissionListQuery } from "@/api/queries";
import { SUBMISSION_STATUSES, type SubmissionStatus } from "@/api/types";
import { RefreshControls } from "@/components/RefreshControls";
import { useAutoRefresh } from "@/lib/autoRefresh";
import { StatusBadge } from "@/components/StatusBadge";
import { formatTimestamp, shortId, statusLabel } from "@/lib/format";
import { Td, Th } from "@/components/Table";
import { PAGE_SIZE } from "@/app/router";

const route = getRouteApi("/submissions");

export function SubmissionsPage() {
  const { formId, status, offset = 0 } = route.useSearch();
  const navigate = useNavigate();
  const autoRefresh = useAutoRefresh((state) => state.enabled);

  const forms = useQuery(formListQuery());
  const submissions = useQuery({
    ...submissionListQuery({ formId, status, limit: PAGE_SIZE, offset }),
    refetchInterval: autoRefresh ? REFRESH_INTERVAL_MS : false,
  });

  const setSearch = (next: {
    formId?: string;
    status?: SubmissionStatus;
    offset?: number;
  }) => {
    void navigate({
      to: "/submissions",
      // A changed filter invalidates the page number, so it resets unless the
      // caller is explicitly paging.
      search: {
        formId: "formId" in next ? next.formId : formId,
        status: "status" in next ? next.status : status,
        offset: next.offset === undefined || next.offset === 0
          ? undefined
          : next.offset,
      },
    });
  };

  const rows = submissions.data?.submissions ?? [];
  const total = submissions.data?.total ?? 0;
  const from = total === 0 ? 0 : offset + 1;
  const to = offset + rows.length;

  return (
    <section>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <h1 className="text-xl font-semibold">Submissions</h1>
        <RefreshControls
          isFetching={submissions.isFetching}
          updatedAt={submissions.dataUpdatedAt}
          onRefresh={() => void submissions.refetch()}
        />
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-4 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-slate-600">Form</span>
          <select
            className="min-w-52 rounded border border-slate-300 px-2 py-1"
            value={formId ?? ""}
            onChange={(event) =>
              setSearch({ formId: event.target.value || undefined })
            }
          >
            <option value="">All forms</option>
            {(forms.data?.forms ?? []).map((form) => (
              <option key={form.formId} value={form.formId}>
                {form.title} ({form.formId})
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-slate-600">Status</span>
          <select
            className="min-w-40 rounded border border-slate-300 px-2 py-1"
            value={status ?? ""}
            onChange={(event) =>
              setSearch({
                status: (event.target.value || undefined) as
                  | SubmissionStatus
                  | undefined,
              })
            }
          >
            <option value="">Any status</option>
            {SUBMISSION_STATUSES.map((value) => (
              <option key={value} value={value}>
                {statusLabel(value)}
              </option>
            ))}
          </select>
        </label>

        {(formId !== undefined || status !== undefined) && (
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 hover:bg-slate-100"
            onClick={() => setSearch({ formId: undefined, status: undefined })}
          >
            Clear filters
          </button>
        )}

        {forms.isError && (
          <span className="text-red-600">Could not load the form list.</span>
        )}
      </div>

      {submissions.isError ? (
        <p className="mt-6 text-red-600">
          Could not load submissions: {String(submissions.error)}
        </p>
      ) : (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[52rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-start text-slate-600">
                <Th>Submission</Th>
                <Th>Form</Th>
                <Th>Device</Th>
                <Th>Status</Th>
                <Th className="text-end">Ops</Th>
                <Th>Received</Th>
              </tr>
            </thead>
            <tbody>
              {rows.map((submission) => (
                <tr
                  key={submission.id}
                  className="border-b border-slate-100 hover:bg-slate-50"
                >
                  <Td>
                    <Link
                      to="/submissions/$submissionId"
                      params={{ submissionId: submission.id }}
                      className="font-mono text-blue-700 hover:underline"
                      title={submission.id}
                    >
                      {shortId(submission.id)}
                    </Link>
                  </Td>
                  <Td>
                    {submission.formTitle}{" "}
                    <span className="text-slate-500">
                      v{submission.formVersion}
                    </span>
                  </Td>
                  <Td className="font-mono text-xs">
                    {submission.originDeviceId ?? "—"}
                  </Td>
                  <Td>
                    <StatusBadge status={submission.status} />
                  </Td>
                  <Td className="text-end tabular-nums">{submission.opCount}</Td>
                  <Td className="whitespace-nowrap">
                    {formatTimestamp(submission.receivedAt)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>

          {rows.length === 0 && !submissions.isPending && (
            <p className="py-8 text-center text-slate-500">
              No submissions match. Push one from a client, or clear the
              filters.
            </p>
          )}
        </div>
      )}

      <div className="mt-4 flex items-center gap-3 text-sm text-slate-600">
        <span>
          {total === 0 ? "0 submissions" : `${from}–${to} of ${total}`}
        </span>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          disabled={offset === 0}
          onClick={() =>
            setSearch({ offset: Math.max(0, offset - PAGE_SIZE) })
          }
        >
          Previous
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-1 disabled:opacity-40"
          disabled={to >= total}
          onClick={() => setSearch({ offset: offset + PAGE_SIZE })}
        >
          Next
        </button>
      </div>
    </section>
  );
}
