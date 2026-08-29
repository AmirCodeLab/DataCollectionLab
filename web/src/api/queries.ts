/** Query definitions. Every fetch the console makes is declared here. */

import { queryOptions } from "@tanstack/react-query";

import { apiGet, apiPost } from "./client";
import type {
  FormListResponse,
  Health,
  ProjectKeyCreate,
  ProjectKeyDetail,
  ProjectKeyListResponse,
  ProjectListResponse,
  SubmissionDetail,
  SubmissionKeysResponse,
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

/** The wrapped content keys for one submission (encryption envelope §4.3).
 *
 * Wrapped copies only. Fetching them costs nothing — the server has never held
 * the private key that opens them, and neither has this browser unless the
 * person at the keyboard loads one.
 */
export const submissionKeysQuery = (submissionId: string) =>
  queryOptions({
    queryKey: ["submission-keys", submissionId],
    queryFn: () =>
      apiGet<SubmissionKeysResponse>(
        `/api/v1/submissions/${encodeURIComponent(submissionId)}/keys`,
      ),
    // Keys arrive with the first op of a submission and never change after.
    staleTime: 5 * 60_000,
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

export const projectListQuery = () =>
  queryOptions({
    queryKey: ["projects"],
    queryFn: () => apiGet<ProjectListResponse>("/api/v1/projects"),
    staleTime: 60_000,
  });

/** A project's recipient keys. Public halves only.
 *
 * `includeRevoked` is what decryption wants: revocation stops future wrapping
 * and cannot unmake the wraps already produced (envelope §8), so a wrap on an
 * old submission may well name a key that has since been retired — and naming
 * its holder is how someone works out which private key to go and find.
 */
export const projectKeysQuery = (projectId: string, includeRevoked = false) =>
  queryOptions({
    queryKey: ["project-keys", projectId, includeRevoked],
    queryFn: () =>
      apiGet<ProjectKeyListResponse>(
        `/api/v1/projects/${encodeURIComponent(projectId)}/keys`,
        { includeRevoked },
      ),
  });

/** Registers a PUBLIC key. There is no endpoint that would take the private one. */
export const addProjectKey = (projectId: string, key: ProjectKeyCreate) =>
  apiPost<ProjectKeyDetail>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/keys`,
    key,
  );
