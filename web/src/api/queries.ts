/** Query definitions. Every fetch the console makes is declared here. */

import { queryOptions } from "@tanstack/react-query";

import { ApiError, apiGet, apiPost, apiPostForm, apiPut } from "./client";
import type {
  AddTeamMemberRequest,
  AreaListResponse,
  BulkAssignRequest,
  BulkAssignResponse,
  CaseListResponse,
  CompileResponse,
  CreateFormRequest,
  CreatePersonRequest,
  CreateRoleRequest,
  CreateTeamRequest,
  DeviceListResponse,
  DraftDocument,
  EnumeratorListResponse,
  ExpressionRequest,
  ExpressionResponse,
  FormListResponse,
  FormSummary,
  FormVersionDocument,
  GrantRequest,
  Health,
  LoginRequest,
  LogoutResponse,
  Me,
  Overview,
  PaletteResponse,
  Person,
  PersonListResponse,
  ProjectKeyCreate,
  ProjectKeyDetail,
  ProjectKeyListResponse,
  ProjectListResponse,
  PublishVersionRequest,
  PublishVersionResponse,
  Role,
  RoleListResponse,
  RolePermissionsRequest,
  SampleUploadResponse,
  SaveDraftRequest,
  SubmissionDetail,
  SubmissionKeysResponse,
  SubmissionListResponse,
  SubmissionStatus,
  Team,
  TeamListResponse,
  QualityRuleListResponse,
  ReviewRequest,
  ReviewResponse,
  SubmissionQualityResponse,
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

/** People, teams and roles (pilot scope §3). What each answers is the
 *  database's decision on the asker's principal: a supervisor's list is
 *  their team, and a write outside their authority comes back 403 with
 *  `outside_your_authority`. */
export const peopleQuery = () =>
  queryOptions({
    queryKey: ["people"],
    queryFn: () => apiGet<PersonListResponse>("/api/v1/people"),
  });

export const teamsQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["teams", projectId],
    queryFn: () => apiGet<TeamListResponse>("/api/v1/teams", { projectId }),
    enabled: projectId !== "",
  });

export const rolesQuery = () =>
  queryOptions({
    queryKey: ["roles"],
    queryFn: () => apiGet<RoleListResponse>("/api/v1/roles"),
  });

export const createPerson = (request: CreatePersonRequest) =>
  apiPost<Person>("/api/v1/people", request);
export const approvePerson = (userId: string) =>
  apiPost<Person>(`/api/v1/people/${userId}/approve`, {});
export const deactivatePerson = (userId: string) =>
  apiPost<Person>(`/api/v1/people/${userId}/deactivate`, {});
export const reactivatePerson = (userId: string) =>
  apiPost<Person>(`/api/v1/people/${userId}/reactivate`, {});
export const grantRole = (userId: string, request: GrantRequest) =>
  apiPost<Person>(`/api/v1/people/${userId}/grants`, request);
export const revokeGrant = (userId: string, grantId: string) =>
  apiPost<Person>(`/api/v1/people/${userId}/grants/${grantId}/revoke`, {});
export const createTeam = (request: CreateTeamRequest) =>
  apiPost<Team>("/api/v1/teams", request);
export const addTeamMember = (teamId: string, request: AddTeamMemberRequest) =>
  apiPost<Team>(`/api/v1/teams/${teamId}/members`, request);
export const createRole = (request: CreateRoleRequest) =>
  apiPost<Role>("/api/v1/roles", request);
export const setRolePermissions = (roleId: string, request: RolePermissionsRequest) =>
  apiPut<Role>(`/api/v1/roles/${roleId}/permissions`, request);

/** The sample and its cases (item 2). What the list holds is what
 *  `dcp_case_in_scope` shows the asker: the unassigned pool to a manager,
 *  a team's cases to its supervisor. Assignment goes through the database's
 *  function, and its refusal is 403 `outside_your_authority`. */
export const casesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["cases", projectId],
    queryFn: () => apiGet<CaseListResponse>("/api/v1/cases", { projectId }),
    enabled: projectId !== "",
  });

/** Supervisor monitoring (item 5). Every figure here is a count over the same
 *  table its list reads, on the same connection under the same principal, so
 *  a number and the rows behind it are one answer. */
export const monitoringOverviewQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["monitoring", "overview", projectId],
    queryFn: () => apiGet<Overview>("/api/v1/monitoring/overview", { projectId }),
    enabled: projectId !== "",
  });

export const monitoringEnumeratorsQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["monitoring", "enumerators", projectId],
    queryFn: () =>
      apiGet<EnumeratorListResponse>("/api/v1/monitoring/enumerators", { projectId }),
    enabled: projectId !== "",
  });

export const monitoringAreasQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["monitoring", "areas", projectId],
    queryFn: () => apiGet<AreaListResponse>("/api/v1/monitoring/areas", { projectId }),
    enabled: projectId !== "",
  });

export const monitoringDevicesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["monitoring", "devices", projectId],
    queryFn: () => apiGet<DeviceListResponse>("/api/v1/monitoring/devices", { projectId }),
    enabled: projectId !== "",
  });

export interface SampleUpload {
  file: File;
  datasetKey: string;
  keyColumns: string[];
  name?: string;
}

export const uploadSample = (projectId: string, upload: SampleUpload) => {
  const form = new FormData();
  form.set("file", upload.file, upload.file.name);
  form.set("datasetKey", upload.datasetKey);
  form.set("keyColumns", upload.keyColumns.join(","));
  if (upload.name) form.set("name", upload.name);
  return apiPostForm<SampleUploadResponse>(`/api/v1/projects/${projectId}/samples`, form);
};

export const assignCases = (request: BulkAssignRequest) =>
  apiPost<BulkAssignResponse>("/api/v1/cases/assign", request);

/** How often an auto-refreshing view re-reads. Field syncs are not fast. */
export const REFRESH_INTERVAL_MS = 10_000;

export interface SubmissionFilters {
  formId?: string;
  status?: SubmissionStatus;
  limit: number;
  offset: number;
  /** The review queue: what a reviewer has something to do about. A filter on
   * this list rather than a route of its own, so the queue and the list it
   * sits in can never disagree (item 6). */
  queue?: boolean;
  /** Whether the submission carries an open violation. Deliberately not "has
   * anything on it": a rule that could not be evaluated is unchecked, not
   * wrong, and the two want different things done about them. */
  flagged?: boolean;
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
        queue: filters.queue,
        flagged: filters.flagged,
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

/** What the rules said about one submission, and what has been decided (item 6).
 *
 * `flags` and `unevaluated` arrive as two lists, and the screen keeps them
 * apart. A reviewer skimming one list reads its length as "how much is wrong",
 * and a rule that could not be evaluated is not something wrong — it is
 * something unchecked.
 */
export const submissionQualityQuery = (submissionId: string) =>
  queryOptions({
    queryKey: ["submission-quality", submissionId],
    queryFn: () =>
      apiGet<SubmissionQualityResponse>(
        `/api/v1/submissions/${encodeURIComponent(submissionId)}/quality`,
      ),
  });

export const reviewSubmission = (submissionId: string, request: ReviewRequest) =>
  apiPost<ReviewResponse>(
    `/api/v1/submissions/${encodeURIComponent(submissionId)}/review`,
    request,
  );

export const qualityRulesQuery = (projectId: string) =>
  queryOptions({
    queryKey: ["quality-rules", projectId],
    queryFn: () =>
      apiGet<QualityRuleListResponse>("/api/v1/quality/rules", { projectId }),
  });
