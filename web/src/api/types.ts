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

export const DIAGNOSTIC_SEVERITYS = ["error", "warning", "info"] as const;

export type DiagnosticSeverity = (typeof DIAGNOSTIC_SEVERITYS)[number];

export const ENVIRONMENT_KINDS = ["development", "staging", "production"] as const;

export type EnvironmentKind = (typeof ENVIRONMENT_KINDS)[number];

export interface EvaluateRequest {
  form: Record<string, unknown>;
  answers?: Record<string, unknown>;
}

export interface EvaluateResponse {
  valid: boolean;
  fields: Record<string, FieldSnapshot>;
  answers: Record<string, unknown>;
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
 * One field after recalculation — `FieldState.to_dict()` in the engine.
 *
 * Written out rather than left as a free-form object because this is the
 * shape a form builder renders: `relevant` and `valid` decide whether a
 * question is on screen and whether it is in error, and a client that has to
 * guess at them is reimplementing the engine to read its output.
 */
export interface FieldSnapshot {
  path: string;
  relevant: boolean;
  required: boolean;
  readOnly: boolean;
  value: unknown;
  valid: boolean;
  errors: string[];
}

export interface FormListResponse {
  forms: FormSummary[];
}

export interface FormSummary {
  id: string;
  formId: string;
  title: string;
  versions: number[];
  archivedAt: string | null;
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
}

export interface PushResponse {
  accepted: string[];
  rejected: RejectedOp[];
  serverCursor: number;
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
] as const;

export type RejectReason = (typeof REJECT_REASONS)[number];

export interface RejectedOp {
  opId: string | null;
  reason: RejectReason;
}

export const SECURITY_MODES = ["standard", "field_level", "project_e2e"] as const;

export type SecurityMode = (typeof SECURITY_MODES)[number];

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
