/** Query definitions. Every fetch the console makes is declared here. */

import { queryOptions } from "@tanstack/react-query";

import { ApiError, apiGet, apiPost, apiPut } from "./client";
import type {
  CompileResponse,
  LoginRequest,
  LogoutResponse,
  Me,
  CreateFormRequest,
  DraftDocument,
  ExpressionRequest,
  ExpressionResponse,
  FormListResponse,
  FormSummary,
  FormVersionDocument,
  PaletteResponse,
  PublishVersionRequest,
  PublishVersionResponse,
  SaveDraftRequest,
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

/** Who this session is. One query, read by the layout to gate every screen
 *  and by each screen to decide what to render; a 401 anywhere invalidates
 *  it (client.ts), which is how a session revoked under the page ends up at
 *  the sign-in form rather than at a screen full of failed requests. */
export const ME_QUERY_KEY = ["auth", "me"] as const;

export const meQuery = () =>
  queryOptions({
    queryKey: ME_QUERY_KEY,
    queryFn: () => apiGet<Me>("/api/v1/auth/me"),
    // A session is not something to poll for; it changes when this tab
    // signs in or out, and both write the cache directly.
    staleTime: Infinity,
    retry: false,
  });

export const login = (request: LoginRequest) => apiPost<Me>("/api/v1/auth/login", request);

export const logout = () => apiPost<LogoutResponse>("/api/v1/auth/logout", {});

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

/** Retires a recipient (encryption envelope §8).
 *
 * A POST, not a DELETE: nothing is deleted. Submissions collected while the key
 * was active stay encrypted to it forever — the server cannot re-wrap what it
 * cannot open — so the row survives to name whose private key opens them. What
 * stops is future wrapping.
 */
export const revokeProjectKey = (projectId: string, keyId: string) =>
  apiPost<ProjectKeyDetail>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/keys/${encodeURIComponent(
      keyId,
    )}/revoke`,
    {},
  );

// --- The form builder (docs/phase3-item0-builder-scope.md) -------------------
//
// Everything the builder knows about a form comes back from these. It holds
// no form logic: the screen plan, the diagnostics and the parsed expression
// are the server's answers, rendered.

/** The unpublished IR, or `null` when no draft exists — a 404 here is a
 *  state, not a failure. */
export const draftQuery = (formId: string) =>
  queryOptions({
    queryKey: ["draft", formId],
    queryFn: async (): Promise<DraftDocument | null> => {
      try {
        return await apiGet<DraftDocument>(
          `/api/v1/forms/${encodeURIComponent(formId)}/draft`,
        );
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null;
        throw error;
      }
    },
    // The builder owns the draft once loaded; a background re-read would
    // overwrite edits with the server's older copy.
    staleTime: Infinity,
    gcTime: 0,
  });

/** Served from the registry, never copied into the console (scope §1). */
export const paletteQuery = () =>
  queryOptions({
    queryKey: ["palette"],
    queryFn: () => apiGet<PaletteResponse>("/api/v1/forms/palette"),
    staleTime: 60 * 60_000,
  });

/** A published version — immutable, so cacheable for as long as the tab lives. */
export const formVersionQuery = (formVersionId: string) =>
  queryOptions({
    queryKey: ["form-version", formVersionId],
    queryFn: () =>
      apiGet<FormVersionDocument>(
        `/api/v1/forms/versions/${encodeURIComponent(formVersionId)}`,
      ),
    staleTime: Infinity,
  });

export const createForm = (request: CreateFormRequest) =>
  apiPost<FormSummary>("/api/v1/forms", request);

export const saveDraft = (formId: string, request: SaveDraftRequest) =>
  apiPut<DraftDocument>(
    `/api/v1/forms/${encodeURIComponent(formId)}/draft`,
    request,
  );

/** The same gate publish runs (`check_publishable`), on demand. A 422 carries
 *  the reasons as `ApiError.detail` — a string, or a list of violations. */
export const compileForm = (form: Record<string, unknown>) =>
  apiPost<CompileResponse>("/api/v1/forms/compile", { form });

/** Text to AST and back (Form IR Appendix A). Always a 200; a bad expression
 *  comes back with `error` and `offset`. */
export const expressionText = (request: ExpressionRequest) =>
  apiPost<ExpressionResponse>("/api/v1/forms/expressions", request);

/** The one route into `form_version`, for a draft exactly as for an import. */
export const publishVersion = (request: PublishVersionRequest) =>
  apiPost<PublishVersionResponse>("/api/v1/forms/versions", request);
