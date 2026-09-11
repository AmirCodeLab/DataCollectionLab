/* GENERATED FILE — DO NOT EDIT.
 *
 * Generated from specs/openapi.json, which is itself generated from the
 * FastAPI app. To change anything here, change the Pydantic model it comes
 * from and run:
 *
 *     python scripts/generate_api_contract.py
 *
 * An edit made here survives exactly until the next run of that command, and
 * in the meantime it says something about the API that is not true.
 */

export interface AddTeamMemberRequest {
  userId: string;
}

export interface AreaListResponse {
  column: string | null;
  areas: AreaProgress[];
}

/**
 * One area's slice **of what the asker may see**, never the area's total.
 *
 * A supervisor's row for an area they share with another team is their part
 * of it. Showing the area's true total would be a leak; labelling their part
 * as the area's total would be a lie. So the label says whose it is (§2,
 * failure 5).
 */
export interface AreaProgress {
  area: string;
  assigned: number;
  covered: number;
}

/** Exactly one of the two: a team, or a person. */
export interface AssignRequest {
  teamId?: string | null;
  userId?: string | null;
}

/**
 * One entry of the assignment statement a device pulls (sync §5,
 * `scope=assignments`): a case held by the device's person, with the sample
 * row behind it so a roster can be preloaded and a settlement shown.
 */
export interface AssignedCase {
  caseId: string;
  caseKey: string | null;
  datasetKey: string | null;
  status: CaseStatus;
  priority: number;
  dueAt: string | null;
  data: Record<string, unknown>;
}

export interface Body_import_xlsform_api_v1_forms_import_post {
  /** An XLSForm .xlsx workbook */
  file: string;
  /** Companion .csv files named by select_one_from_file rows */
  datasets?: string[];
}

export interface Body_publish_dataset_api_v1_projects__project_id__datasets_post {
  /** The reference data, as CSV */
  file: string;
  /** The Form IR key this list is published under — what `choices.dataset` names. The XLSForm importer derives it from the file name and reports what it chose. */
  datasetKey: string;
  /** The column holding each row's identity — what a `select_one_from_file` stores as the answer. Defaults to `name`, which is what XLSForm requires of these files. */
  keyColumn?: string;
  /** Display name for the dataset. Defaults to its key. */
  name?: string | null;
}

export interface Body_upload_sample_api_v1_projects__project_id__samples_post {
  /** The sample, as CSV */
  file: string;
  /** The key this sample is published under, e.g. `hh_sample`. */
  datasetKey: string;
  /** The columns that together identify a row, comma-separated, in the order they compose: `settlementCode,structureId,hhId`. */
  keyColumns: string;
  /** Display name. Defaults to the key. */
  name?: string | null;
}

export interface BulkAssignRequest {
  teamId?: string | null;
  userId?: string | null;
  caseIds: string[];
}

export interface BulkAssignResponse {
  assigned: number;
}

export interface Case {
  id: string;
  projectId: string;
  datasetKey: string | null;
  caseKey: string | null;
  status: CaseStatus;
  priority: number;
  dueAt: string | null;
  data: Record<string, unknown>;
  holder: CaseHolder;
  submissions: number;
}

export interface CaseError {
  reason: CaseFailure;
  message: string;
}

export interface CaseErrorResponse {
  detail: CaseError;
}

export const CASE_FAILURES = [
  "outside_your_authority",
  "not_found",
  "bad_key_row",
  "bad_request",
] as const;

export type CaseFailure = (typeof CASE_FAILURES)[number];

/** The live assignment at one level. */
export interface CaseHolder {
  teamId: string | null;
  teamName: string | null;
  userId: string | null;
  userName: string | null;
  assignedAt: string | null;
}

export interface CaseListResponse {
  cases: Case[];
}

export const CASE_STATUSES = ["open", "closed", "withdrawn"] as const;

export type CaseStatus = (typeof CASE_STATUSES)[number];

/** A Form IR document to compile. Its own formId and version are authoritative. */
export interface CompileRequest {
  form: Record<string, unknown>;
}

export interface CompileResponse {
  formId: string;
  version: number;
  fieldCount: number;
  evaluationOrder: string[];
  warnings: string[];
  neverShown?: string[];
  screens?: ScreenSummary[];
  instancePlans?: Record<string, ScreenSummary[]>;
}

/**
 * A device's content key for one submission, wrapped to every recipient.
 *
 * The key material itself is never here — only copies the server cannot open.
 */
export interface ContentKeyIn {
  contentKeyId: string;
  submissionId: string;
  deviceId: string;
  wraps: WrappedKeyIn[];
}

/** A submission's content key, in the only form the server has it: wrapped. */
export interface ContentKeyView {
  contentKeyId: string;
  deviceId: string;
  wraps: WrappedKeyView[];
}

/**
 * A form row with nothing in it yet — where a draft can start.
 *
 * A draft belongs to a form (`form_draft.form_id` → `form.id`), and until
 * now a form row only ever came from publishing. The builder starts with
 * nothing published, so it needs this first. It creates **no version**:
 * `versions` stays empty until `POST /forms/versions`.
 */
export interface CreateFormRequest {
  projectId: string;
  formId: string;
  title: string;
}

export interface CreatePersonRequest {
  username: string;
  displayName: string;
  password: string;
  roleId: string;
  projectId?: string | null;
  teamId?: string | null;
  membershipKind?: MembershipKind;
}

export interface CreateRoleRequest {
  name: string;
  scopeKind: GrantScope;
  permissions?: Permission[];
}

export interface CreateTeamRequest {
  projectId: string;
  name: string;
  parentTeamId?: string | null;
}

/**
 * What changed between two dataset versions, for one form version.
 *
 * The path that decides field usability. First sync is a one-off at
 * enrolment; this is what happens every week for the life of the project, on
 * whatever connection there is.
 */
export interface DatasetDeltaPage {
  datasetVersionId: string;
  fromDatasetVersionId: string;
  changed: Record<string, string>[];
  deleted: string[];
  columns: string[];
  nextCursor: string | null;
  hasMore: boolean;
}

/**
 * One dataset version a form version is published against.
 *
 * The IR names a dataset by **key** — `"dataset": "districts"` (§3) — and a
 * key is not a version. Resolving it at read time would let a draft opened
 * against form v1 see whatever `districts` happens to be newest, which is the
 * same mistake as validating a v1 answer against v2's choice list.
 *
 * So it is resolved once, here, at publish, and pinned in
 * `form_version_dataset`. A form version is immutable and so is its view of
 * its reference data.
 */
export interface DatasetPin {
  key: string;
  datasetVersionId: string;
}

/**
 * The 409 body: every reason, not the first one.
 *
 * A list rather than a string for the same reason the publish endpoint's is:
 * whoever is fixing the file needs every problem in one pass, and a refusal
 * that names one duplicate key at a time is a refusal somebody meets four
 * times.
 */
export interface DatasetRefusedError {
  detail: string[];
}

/**
 * One page of a dataset version's rows (sync §5).
 *
 * Paged because the first sync is the hard case and cannot be one response:
 * a transfer that cannot resume is a transfer that never finishes on the
 * connections this product exists for.
 *
 * A published version is immutable, so this page can be cached forever and a
 * device that paused for a day resumes into the same ordering it left.
 */
export interface DatasetRowsPage {
  datasetVersionId: string;
  rows: Record<string, string>[];
  nextCursor: string | null;
  hasMore: boolean;
}

/** One day's finished interviews, by the day the enumerator finished. */
export interface DayCount {
  date: string;
  count: number;
}

export const DECISIONS = ["approved", "rejected", "correction_required", "comment"] as const;

export type Decision = (typeof DECISIONS)[number];

/**
 * One entry of a device's dataset manifest (sync §5, `scope=datasets`).
 *
 * Deliberately not the rows. A village list is megabytes and a manifest
 * travels on every sync; the rows are fetched once per version from
 * `GET /datasets/versions/{id}/rows`, the same split that keeps a form
 * manifest to a few hundred bytes.
 *
 * `formVersionId` is on every entry rather than implied, because the pin is
 * per form version: two versions of a form can be deployed at once — an
 * enumerator holding a v2 draft the morning v3 lands — and they may name
 * different versions of the same list. A manifest keyed only by dataset would
 * have to choose between them, which is the choice §3.2 exists to remove.
 */
export interface DeployedDatasetVersion {
  formVersionId: string;
  datasetKey: string;
  datasetVersionId: string;
  version: number;
  rowCount: number;
  checksum: string;
  filterColumns?: string[];
}

/**
 * One entry in a device's form manifest (sync §5, `scope=forms`).
 *
 * Deliberately not the IR. A 52-question form is tens of kilobytes, and a
 * device re-syncs on whatever connection it has; sending every document on
 * every pull would spend exactly the bandwidth this protocol exists to
 * conserve. The manifest says what exists and what it hashes to, and the
 * device fetches only the versions it does not already hold — the same shape
 * resumable upload uses, where the server states what it has and the client
 * sends the rest.
 */
export interface DeployedFormVersion {
  formVersionId: string;
  formId: string;
  version: number;
  title: string;
  irChecksum: string;
  deployedAt: string;
}

export interface DeviceCryptoError {
  reason: RecipientSetFailure;
  message: string;
}

/** 409 from GET /devices/{id}/crypto. */
export interface DeviceCryptoErrorResponse {
  detail: DeviceCryptoError;
}

/**
 * What a device needs before it can encrypt anything (sync §4).
 *
 * Fetched every sync rather than once at registration: rotation (envelope §8)
 * adds keys that a device registered last month would otherwise never wrap
 * to, and a submission wrapped to a stale recipient set is data its intended
 * recovery holder cannot open.
 */
export interface DeviceCryptoResponse {
  deviceId: string;
  projectId: string;
  securityMode: SecurityMode;
  projectKeys: ProjectKeyOut[];
}

export interface DeviceListResponse {
  devices: DeviceStatus[];
}

export const DEVICE_PLATFORMS = ["android", "ios", "desktop", "web"] as const;

export type DevicePlatform = (typeof DEVICE_PLATFORMS)[number];

/** Body of a failed registration, under the usual `detail` key. */
export interface DeviceRegisterError {
  reason: RegisterFailure;
  message: string;
}

/** 403 and 409 from POST /devices. */
export interface DeviceRegisterErrorResponse {
  detail: DeviceRegisterError;
}

export interface DeviceRegisterRequest {
  deviceId: string;
  platform: DevicePlatform;
  osVersion?: string | null;
  appVersion?: string | null;
}

export interface DeviceRegisterResponse {
  deviceId: string;
  projectId: string;
  status: RegisterStatus;
}

export interface DeviceStatus {
  deviceId: string;
  person: string | null;
  platform: string;
  appVersion: string | null;
  lastSyncAt: string | null;
  reportedPendingOps: number | null;
  reportedAt: string | null;
}

export const DIAGNOSTIC_SEVERITYS = ["error", "warning", "info"] as const;

export type DiagnosticSeverity = (typeof DIAGNOSTIC_SEVERITYS)[number];

/**
 * A form's unpublished IR.
 *
 * `revision` is what a caller sends back on the next save. It is not a
 * version number and cannot become one — see `FormDraft`.
 */
export interface DraftDocument {
  formId: string;
  ir: Record<string, unknown>;
  revision: number;
  updatedAt: string;
  updatedBy?: string | null;
  testCases?: TestCase[];
}

export interface EnumeratorListResponse {
  enumerators: EnumeratorProgress[];
}

export interface EnumeratorProgress {
  userId: string;
  displayName: string;
  assigned: number;
  covered: number;
  finalized: number;
  lastSyncAt: string | null;
}

export const ENVIRONMENT_KINDS = ["development", "staging", "production"] as const;

export type EnvironmentKind = (typeof ENVIRONMENT_KINDS)[number];

/**
 * What the author expects to be true of one path after the steps.
 *
 * Each field is optional and only the ones present are checked, so a case
 * can say "hidden" without saying what the value is.
 */
export interface Expectation {
  path: string;
  relevant?: boolean | null;
  valid?: boolean | null;
  value?: unknown;
  checkValue?: boolean;
}

export const EXPORT_FORMATS = ["csv", "xlsx", "dta", "sav"] as const;

export type ExportFormat = (typeof EXPORT_FORMATS)[number];

export const EXPORT_SHAPES = ["long", "wide"] as const;

export type ExportShape = (typeof EXPORT_SHAPES)[number];

/**
 * More submissions than one synchronous export will do.
 *
 * Carries the numbers rather than only prose, because the useful thing a
 * console can do with this is say how much to narrow by.
 */
export interface ExportTooLarge {
  /** submissions the filter selected */
  found: number;
  /** the most this endpoint will export at once */
  limit: number;
  message: string;
}

/** 413 from GET /exports/{formId}. */
export interface ExportTooLargeResponse {
  detail: ExportTooLarge;
}

/**
 * A value will not fit the format that was asked for.
 *
 * Names the formats that *do* hold it, because that is what a caller acts on:
 * an SPSS user with one very long answer needs a different flag, not a
 * truncated file and not a 500.
 */
export interface ExportValueTooLong {
  /** the column in the file, as `storedAs` names it */
  column: string;
  /** the value's length in UTF-8 bytes */
  found: number;
  /** the most this format's strings hold, in bytes */
  limit: number;
  format: ExportFormat;
  message: string;
}

/** 409 from GET /exports/{formId}. */
export interface ExportValueTooLongResponse {
  detail: ExportValueTooLong;
}

export interface ExpressionRequest {
  text?: string | null;
  expression?: Record<string, unknown> | null;
  selfPath?: string | null;
  rowScope?: boolean;
}

/**
 * The AST and its canonical text, or where the text went wrong.
 *
 * Both directions in one shape because a code field needs both: it renders an
 * existing expression to show the author, and parses what they type back.
 */
export interface ExpressionResponse {
  expression?: Record<string, unknown> | null;
  text?: string | null;
  error?: string | null;
  offset?: number | null;
}

export interface FlagView {
  id: string;
  ruleId: string | null;
  ruleName: string | null;
  severity: string;
  outcome: Outcome;
  detail: Record<string, unknown>;
  path: string | null;
  createdAt: string;
  resolvedAt: string | null;
}

export interface FormListResponse {
  forms: FormSummary[];
}

export interface FormSummary {
  id: string;
  formId: string;
  projectId: string;
  title: string;
  versions: number[];
  archivedAt: string | null;
  hasDraft?: boolean;
  latestVersionId?: string | null;
}

/**
 * One published version and its Form IR (sync §5).
 *
 * What a device fetches once the manifest names a version it does not hold.
 * Immutable: the id addresses a row that can never be rewritten
 * (specs/erd-v0.1.md §4), so a client may cache it forever.
 */
export interface FormVersionDocument {
  formVersionId: string;
  formId: string;
  version: number;
  title: string;
  irChecksum: string;
  publishedAt: string | null;
  form: Record<string, unknown>;
}

/** A role held in a scope. */
export interface Grant {
  id: string;
  roleId: string;
  roleName: string;
  scopeKind: GrantScope;
  projectId: string | null;
  teamId: string | null;
  teamName: string | null;
  grantedAt: string;
}

export interface GrantRequest {
  roleId: string;
  projectId?: string | null;
  teamId?: string | null;
}

export const GRANT_SCOPES = ["organization", "project", "team"] as const;

export type GrantScope = (typeof GRANT_SCOPES)[number];

export interface HTTPValidationError {
  detail?: ValidationError[];
}

/**
 * The liveness probe.
 *
 * The console polls this to tell "the API is down" apart from "the API is up
 * and there is no data", which are the same empty screen otherwise.
 */
export interface Health {
  status: string;
  environment: string;
}

/**
 * Proof that nothing was dropped in silence.
 *
 * Every non-empty cell in the workbook either produced part of the form or is
 * named by a diagnostic above. A cell in neither fails the import outright
 * rather than reaching this response — see the coverage ledger.
 *
 * It cannot tell you the workbook had anything in it. An empty sheet has no
 * cells to account for, so `cells: 0` satisfies the check perfectly; that is
 * why a form with no questions is refused at publish rather than merely noted.
 */
export interface ImportCoverage {
  cells: number;
  consumed: number;
  reported: number;
}

/**
 * One companion CSV, read — what it is and what the form does with it.
 *
 * Deliberately without the rows. This is the answer to "what would this
 * become?", and a village list would make the response several megabytes on
 * an endpoint whose whole point is to be cheap enough to call on every edit.
 * The caller already has the file; `POST /projects/{id}/datasets` is where
 * the bytes go.
 */
export interface ImportDataset {
  key: string;
  fileName: string;
  rowCount: number;
  columns: string[];
  valueColumn: string;
  labelColumns?: Record<string, string>;
  columnsUsed?: string[];
  usedBy?: string[];
  checksum: string;
  encoding: string;
}

export interface ImportDiagnostic {
  severity: DiagnosticSeverity;
  code: string;
  message: string;
  sheet?: string | null;
  row?: number | null;
  column?: string | null;
  cellValue?: string | null;
  nodeId?: string | null;
  remedy?: string | null;
}

/**
 * The IR, and everything that did not survive the trip.
 *
 * The form is returned even when it cannot be published, deliberately: an
 * author needs every problem in one pass rather than one per round trip, and
 * a form they can look at is how they find the next one.
 */
export interface ImportFormResponse {
  publishable: boolean;
  form: Record<string, unknown>;
  summary: ImportSummary;
  diagnostics: ImportDiagnostic[];
  coverage: ImportCoverage;
  instrumentation: ImportInstrumentation;
  datasets?: ImportDataset[];
  reportMarkdown: string;
}

/**
 * What this form needed that the platform does not have.
 *
 * Separate from the diagnostics because it answers a different question: a
 * diagnostic tells one author about one form, and this says which XPath
 * functions and question types real forms reach for. That is the priority
 * order for what to build next, and counting it beats guessing it.
 */
export interface ImportInstrumentation {
  unsupportedFunctions?: Record<string, number>;
  unsupportedTypes?: Record<string, number>;
  uncollectableTypes?: Record<string, number>;
}

/**
 * How a version got here, stored with it and never recomputed.
 *
 * Sent by whoever imported the spreadsheet and published the result, so the
 * question "why does this form not have the question I put in row 40?" is
 * answerable six months later from the database rather than from an email
 * somebody may still have.
 *
 * Optional on a publish: a form written as IR by hand was not imported, and
 * recording nothing is the honest answer for it. Half a record is refused by
 * the database (`form_version_import_complete_check`), because a partial one
 * looks like a whole one.
 */
export interface ImportRecord {
  sourceName: string;
  sourceSha256: string;
  importerVersion: string;
  diagnostics: ImportDiagnostic[];
}

export interface ImportSummary {
  questions: number;
  nodes: number;
  surveyRows: number;
  languages: string[];
  errors: number;
  warnings: number;
  notes: number;
}

export const KEY_REGISTRATION_FAILURES = [
  "project_not_found",
  "project_archived",
  "degenerate_public_key",
  "duplicate_public_key",
  "test_only_key",
  "key_not_found",
  "last_active_key",
] as const;

export type KeyRegistrationFailure = (typeof KEY_REGISTRATION_FAILURES)[number];

export const KEY_ROLES = ["primary", "backup", "recovery"] as const;

export type KeyRole = (typeof KEY_ROLES)[number];

export interface LoginError {
  reason: LoginFailure;
  message: string;
}

export interface LoginErrorResponse {
  detail: LoginError;
}

export const LOGIN_FAILURES = [
  "invalid_credentials",
  "pending_approval",
  "deactivated",
  "no_membership",
  "device_unknown",
  "device_revoked",
  "device_required",
] as const;

export type LoginFailure = (typeof LOGIN_FAILURES)[number];

export interface LoginRequest {
  username: string;
  password: string;
  kind?: SessionKind;
  deviceId?: string | null;
  organization?: string | null;
}

export interface LogoutResponse {
  status: "logged_out";
}

/**
 * Who this session is, and what it may do. Everything a screen needs to
 * decide what to render; nothing it needs to keep.
 */
export interface Me {
  userId: string;
  username: string | null;
  displayName: string;
  organizationId: string;
  organizationSlug: string;
  sessionKind: SessionKind;
  deviceId: string | null;
  scopeKind: ScopeKind;
  permissions: Permission[];
  projectIds: string[];
  teamIds: string[];
  expiresAt: string;
}

/**
 * One chunk stored. Re-sending a chunk already held is a success, not an
 * error: a client that lost the response has no way to tell the difference,
 * and making it retry-safe is cheaper than making it careful.
 */
export interface MediaChunkResponse {
  mediaId: string;
  chunkIndex: number;
  sizeBytes: number;
  receivedChunks: number;
  chunkCount: number;
}

export interface MediaCompleteRequest {
  ciphertextHash: string;
}

export interface MediaCompleteResponse {
  mediaId: string;
  hash: string;
  sizeBytes: number;
  chunkCount: number;
  status: MediaStatus;
}

/** The wrapped media keys for one file (envelope §6, §7). */
export interface MediaKeysView {
  mediaId: string;
  contentKeyId: string | null;
  wraps: MediaWrappedKeyView[];
}

/** Per-project capture settings (see project.media_* in 002_media.sql). */
export interface MediaPolicy {
  imageMaxDimension: number;
  imageQuality: number;
  gpsMaxAccuracyM: number;
}

export interface MediaPolicyResponse {
  projectId: string;
  chunkSize: number;
  policy: MediaPolicy;
}

/** Change one or more settings. Omitted fields are left alone. */
export interface MediaPolicyUpdate {
  imageMaxDimension?: number | null;
  imageQuality?: number | null;
  gpsMaxAccuracyM?: number | null;
}

export const MEDIA_STATUSES = ["pending", "uploading", "complete", "failed"] as const;

export type MediaStatus = (typeof MEDIA_STATUSES)[number];

/** A refusal a client can branch on, not just a status code. */
export interface MediaUploadError {
  reason: MediaUploadFailure;
  message: string;
}

/**
 * FastAPI sends `{"detail": ...}`; this is that envelope, not the payload
 * inside it.
 */
export interface MediaUploadErrorResponse {
  detail: MediaUploadError;
}

export const MEDIA_UPLOAD_FAILURES = [
  "submission_not_found",
  "device_not_authorized",
  "media_conflict",
  "session_not_found",
  "session_expired",
  "chunk_out_of_range",
  "chunk_size_mismatch",
  "chunks_missing",
  "hash_mismatch",
  "unknown_recipient",
  "unwrapped_media_key",
] as const;

export type MediaUploadFailure = (typeof MEDIA_UPLOAD_FAILURES)[number];

/**
 * Open — or reopen — an upload for one file.
 *
 * Idempotent on `mediaId`. Calling it again for a file already part-uploaded
 * is exactly how resumption starts: the response says which chunks the server
 * already holds, and the client sends the rest. That is why there is no
 * separate "session status" endpoint — a resuming client has to make this call
 * anyway, and a second way to ask the same question is a second thing that can
 * disagree.
 */
export interface MediaUploadSessionRequest {
  mediaId: string;
  submissionId: string;
  deviceId: string;
  opId?: string | null;
  fieldPath?: string | null;
  mimeType: string;
  sizeBytes: number;
  chunkCount: number;
  encrypted: boolean;
  contentKeyId?: string | null;
  wraps?: MediaWrappedKeyIn[];
}

/** Where to send the chunks, and which ones are already here. */
export interface MediaUploadSessionResponse {
  uploadId: string;
  mediaId: string;
  chunkSize: number;
  chunkCount: number;
  receivedChunks: number[];
  status: MediaStatus;
  expiresAt: string;
}

/** One file as the console sees it. */
export interface MediaView {
  mediaId: string;
  submissionId: string;
  opId: string | null;
  fieldPath: string | null;
  deviceId: string | null;
  mimeType: string;
  sizeBytes: number;
  chunkCount: number;
  receivedChunks: number;
  status: MediaStatus;
  encrypted: boolean;
  ciphertextHash: string | null;
  contentKeyId: string | null;
  resolved: boolean;
  createdAt: string;
  uploadedAt: string | null;
}

/** The media key wrapped to one recipient project key (envelope §6, §4.4). */
export interface MediaWrappedKeyIn {
  projectKeyId: string;
  ephemeralPublic: string;
  nonce: string;
  wrappedKey: string;
}

export interface MediaWrappedKeyView {
  projectKeyId: string;
  ephemeralPublic: string;
  nonce: string;
  wrappedKey: string;
}

export const MEMBERSHIP_KINDS = ["permanent", "temporary"] as const;

export type MembershipKind = (typeof MEMBERSHIP_KINDS)[number];

export const MEMBERSHIP_STATUSES = ["active", "pending_approval", "deactivated"] as const;

export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number];

/**
 * The body of a refusal that carries prose and nothing to branch on.
 *
 * `{"detail": "submission not found"}`. Used where there is exactly one way
 * to fail and the status code already says which: a 404 on a read endpoint.
 * Anything a client must branch on gets a `reason` field instead — see
 * `DeviceRegisterError` and `ProjectKeyError` in `modules/projects/schemas.py`.
 */
export interface MessageError {
  detail: string;
}

export const OP_KINDS = [
  "set",
  "unset",
  "repeat_add",
  "repeat_delete",
  "finalize",
  "reopen",
] as const;

export type OpKind = (typeof OP_KINDS)[number];

export const OUTCOMES = ["violation", "not_evaluated"] as const;

export type Outcome = (typeof OUTCOMES)[number];

export interface Overview {
  scopeKind: ScopeKind;
  scopeLabel: string;
  casesAssigned: number;
  casesCovered: number;
  submissions: number;
  uncasedSubmissions: number;
  devices: number;
  flagsOutstanding: number | null;
  perDay: DayCount[];
}

/**
 * The question palette, served rather than copied.
 *
 * `specs/collectable-types-v0.1.json` exists to stop two hand-maintained
 * copies drifting, and its own header names `SUBMISSION_STATUSES` as the case
 * this repository already paid for. Until now the console could not read it
 * at all — it got `uncollectableTypes` as a count on the import response and
 * nothing else — so a builder would have had to hard-code the list, which is
 * the second copy the registry was written to prevent.
 */
export interface PaletteResponse {
  version: string;
  types: PaletteType[];
  choiceSources: PaletteType[];
}

/**
 * One dataType, and whether a client can actually present it.
 *
 * `status` is `collectable` or `in_spec_only`, and the distinction is the
 * whole reason this endpoint exists: a dataType can be in the IR, carry a
 * conformance vector and be evaluated identically by both engines, and still
 * arrive on a phone as a label with empty space under it. That was defect 7.
 *
 * A builder shows the `in_spec_only` ones **disabled, carrying `note`** —
 * which is the registry's own sentence about that type, not a sentence the
 * console invented. The day `time` ships, the palette gains it with no
 * console change.
 */
export interface PaletteType {
  dataType: string;
  status: string;
  note?: string | null;
}

export interface PeopleError {
  reason: PeopleFailure;
  message: string;
}

export interface PeopleErrorResponse {
  detail: PeopleError;
}

export const PEOPLE_FAILURES = [
  "outside_your_authority",
  "not_found",
  "already_exists",
] as const;

export type PeopleFailure = (typeof PEOPLE_FAILURES)[number];

export const PERMISSIONS = [
  "user.create",
  "user.approve",
  "user.deactivate",
  "user.assign_role",
  "team.manage",
  "sample.upload",
  "sample.assign",
  "form.edit",
  "form.publish",
  "form.deploy",
  "submission.view",
  "submission.review",
  "export.download",
  "device.revoke",
  "project.manage",
] as const;

export type Permission = (typeof PERMISSIONS)[number];

/** A person as the asker may see them: the policies decide who is here. */
export interface Person {
  id: string;
  username: string | null;
  displayName: string;
  membershipStatus: MembershipStatus;
  membershipKind: MembershipKind;
  createdBy: string | null;
  createdByName: string | null;
  createdAt: string;
  approvedByName: string | null;
  approvedAt: string | null;
  deactivatedAt: string | null;
  lastLoginAt: string | null;
  grants: Grant[];
  teams: TeamMembership[];
}

export interface PersonListResponse {
  people: Person[];
}

/**
 * A new project (gate 1, A2 and A5).
 *
 * An organisation is provisioned on the server, because creating one needs a
 * privilege no request may hold. A project is not: by the time anybody asks
 * for one, an administrator exists and can be refused like anybody else.
 *
 * `securityMode` is chosen here and is not changed afterwards. It decides
 * whether the server ever holds a readable answer, and changing it later
 * would leave a project whose submissions mean two different things.
 */
export interface ProjectCreate {
  name: string;
  slug: string;
  securityMode?: SecurityMode;
}

export const PROJECT_CREATE_FAILURES = ["slug_taken", "organization_unknown"] as const;

export type ProjectCreateFailure = (typeof PROJECT_CREATE_FAILURES)[number];

export interface ProjectCreateRefusal {
  reason: ProjectCreateFailure;
  message: string;
}

export interface ProjectCreateRefusalResponse {
  detail: ProjectCreateRefusal;
}

/**
 * A public key being registered as a recipient (envelope §4.1).
 *
 * `extra="forbid"`, deliberately. The private key is generated in the browser
 * and downloaded by the user; it must never reach the server. A client that
 * sends one — under any field name — gets a 422 naming the field rather than
 * a 201 and a silently ignored secret sitting in a request log.
 *
 * An X25519 private key is 32 bytes and so is a public key, so no server can
 * tell one from the other by looking. That is exactly why the guarantee has to
 * be structural: the server never asks for a private key, accepts no field
 * that could carry one, and refuses anything shaped like a key container.
 */
export interface ProjectKeyCreate {
  publicKey: string;
  role: KeyRole;
  label: string;
}

/** A stored recipient key, as the console lists it. */
export interface ProjectKeyDetail {
  keyId: string;
  publicKey: string;
  role: KeyRole;
  label: string;
  projectId: string;
  createdAt: string;
  revokedAt: string | null;
}

export interface ProjectKeyError {
  reason: KeyRegistrationFailure;
  message: string;
}

/** 404, 409 and 422 from the project key endpoints. */
export interface ProjectKeyErrorResponse {
  detail: ProjectKeyError;
}

export interface ProjectKeyListResponse {
  projectId: string;
  securityMode: SecurityMode;
  keys: ProjectKeyDetail[];
}

/**
 * One recipient a content key must be wrapped to (envelope §4.1).
 *
 * Public keys only. The private half is generated in the browser at project
 * creation, downloaded by the user, and never transmitted to the server —
 * so there is nothing secret to leak here.
 */
export interface ProjectKeyOut {
  keyId: string;
  publicKey: string;
  role: KeyRole;
  label: string;
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
}

/** One project, enough for the console to name it and route to it. */
export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  securityMode: SecurityMode;
  activeKeyCount: number;
  createdAt: string;
  archivedAt: string | null;
}

/** One immutable dataset version (Form IR §3, sync §5). */
export interface PublishDatasetResponse {
  datasetId: string;
  datasetVersionId: string;
  datasetKey: string;
  version: number;
  rowCount: number;
  checksum: string;
  created: boolean;
  warnings: string[];
  publishedAt: string | null;
}

export interface PublishVersionRequest {
  projectId: string;
  form: Record<string, unknown>;
  title?: string | null;
  publishedBy?: string | null;
  deployTo?: EnvironmentKind[];
  importRecord?: ImportRecord | null;
  datasets?: DatasetPin[];
}

export interface PublishVersionResponse {
  id: string;
  formId: string;
  version: number;
  irChecksum: string;
  publishedAt: string | null;
  created: boolean;
  warnings: string[];
  deployments: EnvironmentKind[];
  datasets?: DatasetPin[];
}

export interface PullResponse {
  ops: PulledOp[];
  tombstones: PulledTombstone[];
  forms: DeployedFormVersion[];
  assignments?: AssignedCase[] | null;
  returned?: ReturnedWork[] | null;
  datasets?: DeployedDatasetVersion[] | null;
  nextCursor: number;
  hasMore: boolean;
}

export interface PulledOp {
  opId: string;
  submissionId: string;
  formId: string;
  formVersion: number;
  kind: OpKind;
  path: string | null;
  value: unknown;
  valueCiphertext: string | null;
  contentKeyId: string | null;
  nonce: string | null;
  deviceId: string;
  actorId: string | null;
  counter: number;
  wallClock: string;
  serverSeq: number;
}

export interface PulledTombstone {
  id: string;
  subjectType: TombstoneSubject;
  subjectId: string;
  submissionId: string | null;
  path: string | null;
  deviceId: string | null;
  counter: number | null;
  createdAt: string;
  expiresAt: string | null;
  serverSeq: number;
}

export interface PushRequest {
  deviceId: string;
  ops: Record<string, unknown>[];
  keys?: ContentKeyIn[];
  pendingOps?: number | null;
}

export interface PushResponse {
  accepted: string[];
  rejected: RejectedOp[];
  serverCursor: number;
}

export interface QualityRuleIn {
  name: string;
  definition: Record<string, unknown>;
  severity?: Severity;
  enabled?: boolean;
  formId?: string | null;
}

export interface QualityRuleListResponse {
  rules: QualityRuleOut[];
}

export interface QualityRuleOut {
  id: string;
  name: string;
  definition: Record<string, unknown>;
  severity: string;
  enabled: boolean;
  formId: string | null;
  createdAt: string;
}

export const RECIPIENT_SET_FAILURES = ["test_only_key"] as const;

export type RecipientSetFailure = (typeof RECIPIENT_SET_FAILURES)[number];

export const REGISTER_FAILURES = [
  "project_not_found",
  "project_ambiguous",
  "project_mismatch",
  "device_revoked",
] as const;

export type RegisterFailure = (typeof REGISTER_FAILURES)[number];

export const REGISTER_STATUSES = ["registered", "already_registered"] as const;

export type RegisterStatus = (typeof REGISTER_STATUSES)[number];

export const REJECT_REASONS = [
  "unknown_form_version",
  "not_authorized",
  "submission_closed",
  "malformed",
  "unknown_content_key",
  "nonce_reused",
  "not_assigned",
] as const;

export type RejectReason = (typeof REJECT_REASONS)[number];

export interface RejectedOp {
  opId: string | null;
  reason: RejectReason;
}

/**
 * A submission a reviewer has handed back, with the reason (item 6).
 *
 * It travels in the pull because that is the only stream a handset already
 * consumes, and it is a **statement** rather than an op for one reason:
 * `submission_op.device_id` is NOT NULL and `UNIQUE (device_id, counter)` is
 * per device, so a server-authored op has no device to be authored by and no
 * counter it can take without colliding with whatever the enumerator's
 * handset is about to push. The `reopen` op is authored by the device that
 * holds the work, when the enumerator opens it — so the op log stays a
 * record of what devices did.
 *
 * The reason is carried, not referenced. Work sent back without one arrives
 * as a repeat of the same visit.
 */
export interface ReturnedWork {
  submissionId: string;
  status: string;
  caseId: string | null;
  formId: string;
  formVersion: number;
  reason: string | null;
  decidedAt: string;
  decidedBy: string | null;
}

export interface ReviewEntry {
  id: string;
  decision: Decision;
  comment: string | null;
  reviewer: string | null;
  createdAt: string;
}

/** A refusal a client can act on, in the shape items 2 and 4 use. */
export interface ReviewRefusal {
  reason: ReviewRefusalReason;
  message: string;
}

export const REVIEW_REFUSAL_REASONS = [
  "unknown_decision",
  "not_found",
  "reason_required",
  "not_allowed",
] as const;

export type ReviewRefusalReason = (typeof REVIEW_REFUSAL_REASONS)[number];

export interface ReviewRefusalResponse {
  detail: ReviewRefusal;
}

export interface ReviewRequest {
  decision: Decision;
  comment?: string | null;
}

export interface ReviewResponse {
  reviewId: string;
  status: string;
  returnsWork: boolean;
}

export interface Role {
  id: string;
  name: string;
  scopeKind: ScopeKind;
  builtin: boolean;
  permissions: Permission[];
  grantable: boolean;
}

export interface RoleListResponse {
  roles: Role[];
}

export interface RolePermissionsRequest {
  permissions: Permission[];
}

export interface RuleRefusal {
  reason: RuleRefusalReason;
  message: string;
}

export const RULE_REFUSAL_REASONS = [
  "invalid_expression",
  "unknown_form",
  "not_found",
] as const;

export type RuleRefusalReason = (typeof RULE_REFUSAL_REASONS)[number];

export interface RuleRefusalResponse {
  detail: RuleRefusal;
}

/**
 * What one upload did: the dataset version it published (idempotent by
 * content) and the cases it made, reopened and withdrew.
 */
export interface SampleUploadResponse {
  datasetKey: string;
  datasetVersionId: string;
  version: number;
  rowCount: number;
  createdVersion: boolean;
  keyColumns: string[];
  casesCreated: number;
  casesReopened: number;
  casesWithdrawn: number;
  warnings: string[];
}

export interface SaveDraftRequest {
  ir: Record<string, unknown>;
  expectedRevision?: number | null;
  updatedBy?: string | null;
  testCases?: TestCase[] | null;
}

export const SCOPE_KINDS = ["organization", "project", "team", "none"] as const;

export type ScopeKind = (typeof SCOPE_KINDS)[number];

/**
 * One screen of the plan, as §11.1 partitions it.
 *
 * Written out rather than left free-form for the reason the builder exists:
 * a console that derived this itself would be a **third** implementation of
 * §11.1, unreachable by any vector, deciding what an author believes their
 * form does. §11.1 has six rules and three of them surprise people — a
 * calculate produces no screen, a field-list flattens nested plain groups,
 * and a repeat is exactly one screen at any instance count. The plan is the
 * only honest way to show an author which of those applied to them.
 */
export interface ScreenSummary {
  index: number;
  kind: string;
  questionIds: string[];
  repeatId?: string | null;
  groupId?: string | null;
  sectionId?: string | null;
}

export const SECURITY_MODES = ["standard", "field_level", "project_e2e"] as const;

export type SecurityMode = (typeof SECURITY_MODES)[number];

export const SESSION_KINDS = ["console", "app"] as const;

export type SessionKind = (typeof SESSION_KINDS)[number];

export const SEVERITYS = ["info", "warning", "error"] as const;

export type Severity = (typeof SEVERITYS)[number];

export interface SubmissionDetail {
  id: string;
  projectId: string;
  formId: string;
  formTitle: string;
  formVersion: number;
  status: SubmissionStatus;
  originDeviceId: string | null;
  createdBy: string | null;
  startedAt: string | null;
  finalizedAt: string | null;
  receivedAt: string;
  opCount: number;
  state: SubmissionStateView | null;
  ops: SubmissionOpView[];
  opsTruncated: boolean;
}

/**
 * Every wrapped key needed to decrypt one submission (envelope §7).
 *
 * A submission built by several devices has one content key per device, all
 * wrapped to the same recipients, so a single private key opens every one.
 * Handing these out costs nothing: the server has never held the private key
 * that opens them, and neither has whoever is asking, unless they own it.
 */
export interface SubmissionKeysResponse {
  submissionId: string;
  contentKeys: ContentKeyView[];
}

export interface SubmissionListResponse {
  submissions: SubmissionSummary[];
  total: number;
  limit: number;
  offset: number;
}

/** Every file belonging to one submission, resolved or not. */
export interface SubmissionMediaResponse {
  submissionId: string;
  media: MediaView[];
  keys: MediaKeysView[];
  pendingCount: number;
}

/** One row of the raw op log. */
export interface SubmissionOpView {
  id: string;
  kind: OpKind;
  path: string | null;
  value: unknown;
  encrypted: boolean;
  valueCiphertext: string | null;
  contentKeyId: string | null;
  nonce: string | null;
  deviceId: string;
  actorId: string | null;
  counter: number;
  wallClock: string;
  receivedAt: string;
  serverSeq: number;
}

export interface SubmissionQualityResponse {
  flags: FlagView[];
  unevaluated: FlagView[];
  reviews: ReviewEntry[];
}

/** The materialised fold: current value per field path. */
export interface SubmissionStateView {
  data: Record<string, unknown>;
  opHighWater: number;
  computedAt: string;
}

export const SUBMISSION_STATUSES = [
  "draft",
  "finalized",
  "in_review",
  "approved",
  "rejected",
  "correction_required",
] as const;

export type SubmissionStatus = (typeof SUBMISSION_STATUSES)[number];

/** One row of the submission list. */
export interface SubmissionSummary {
  id: string;
  formId: string;
  formTitle: string;
  formVersion: number;
  status: SubmissionStatus;
  originDeviceId: string | null;
  opCount: number;
  receivedAt: string;
}

export interface Team {
  id: string;
  projectId: string;
  name: string;
  parentTeamId: string | null;
  members: TeamMember[];
}

export interface TeamListResponse {
  teams: Team[];
}

export interface TeamMember {
  userId: string;
  displayName: string;
  membershipStatus: MembershipStatus;
}

export interface TeamMembership {
  projectId: string;
  teamId: string | null;
  teamName: string | null;
}

/**
 * An author's test case (builder scope §4, "Test mode").
 *
 * Owned by the author, about one form, and supposed to change when the form
 * changes. **Not a conformance vector and never stored as one** — see
 * `migrations/schema/007_form_draft_test_cases.sql`. The server stores and
 * returns these; the builder runs them through the engine.
 */
export interface TestCase {
  id: string;
  name: string;
  steps?: TestStep[];
  expectations?: Expectation[];
}

/** One step of an author's test case: what the enumerator would do. */
export interface TestStep {
  kind: TestStepKind;
  path?: string | null;
  value?: unknown;
  repeatId?: string | null;
  instanceId?: string | null;
}

export const TEST_STEP_KINDS = ["set", "addRow", "deleteRow"] as const;

export type TestStepKind = (typeof TEST_STEP_KINDS)[number];

export const TOMBSTONE_SUBJECTS = [
  "submission",
  "repeat_instance",
  "case",
  "entity",
  "media",
] as const;

export type TombstoneSubject = (typeof TOMBSTONE_SUBJECTS)[number];

export interface ValidationError {
  loc: (string | number)[];
  msg: string;
  type: string;
  input?: unknown;
  ctx?: Record<string, unknown>;
}

/** One content key wrapped to one recipient project key (envelope §4.3). */
export interface WrappedKeyIn {
  projectKeyId: string;
  ephemeralPublic: string;
  nonce: string;
  wrappedKey: string;
}

/** One content key wrapped to one recipient project key (envelope §4.3). */
export interface WrappedKeyView {
  projectKeyId: string;
  ephemeralPublic: string;
  nonce: string;
  wrappedKey: string;
}
