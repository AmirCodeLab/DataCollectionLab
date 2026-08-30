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

export interface EvaluateRequest {
  form: Record<string, unknown>;
  answers?: Record<string, unknown>;
}

export interface EvaluateResponse {
  valid: boolean;
  fields: Record<string, FieldSnapshot>;
  answers: Record<string, unknown>;
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

export interface PublishVersionRequest {
  projectId: string;
  form: Record<string, unknown>;
  title?: string | null;
  publishedBy?: string | null;
}

export interface PublishVersionResponse {
  id: string;
  formId: string;
  version: number;
  irChecksum: string;
  publishedAt: string | null;
  created: boolean;
  warnings: string[];
}

export interface PullResponse {
  ops: PulledOp[];
  tombstones: PulledTombstone[];
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
