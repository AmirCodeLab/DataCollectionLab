/** Query definitions. Every fetch the console makes is declared here. */

import { queryOptions } from "@tanstack/react-query";

import { apiGet } from "./client";
import type {
  FormListResponse,
  Health,
  SubmissionDetail,
  SubmissionListResponse,
  SubmissionStatus,
} from "./types";

/** How often an auto-refreshing view re-reads. Field syncs are not fast. */
export const REFRESH_INTERVAL_MS = 10_000;

export interface SubmissionFilters {
  formId?: string;
  status?: SubmissionStatus;
  limit: number;
  offset: number;
}

export const submissionListQuery = (filters: SubmissionFilters) =>
  queryOptions({
    queryKey: ["submissions", filters],
    queryFn: () =>
      apiGet<SubmissionListResponse>("/api/v1/submissions", {
        formId: filters.formId,
        status: filters.status,
        limit: filters.limit,
        offset: filters.offset,
      }),
    // A page that is one refresh old is better than a flash of empty table.
    placeholderData: (previous) => previous,
  });

export const submissionQuery = (submissionId: string) =>
  queryOptions({
    queryKey: ["submission", submissionId],
    queryFn: () =>
      apiGet<SubmissionDetail>(
        `/api/v1/submissions/${encodeURIComponent(submissionId)}`,
      ),
  });

export const formListQuery = () =>
  queryOptions({
    queryKey: ["forms"],
    queryFn: () => apiGet<FormListResponse>("/api/v1/forms"),
    // Forms change when someone publishes one, not between refreshes.
    staleTime: 5 * 60_000,
  });

export const healthQuery = () =>
  queryOptions({
    queryKey: ["health"],
    queryFn: () => apiGet<Health>("/health"),
    refetchInterval: 30_000,
  });
