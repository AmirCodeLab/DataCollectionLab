/** Wire types, mirroring the schemas.py files under backend/app/modules.
 *
 * Hand-written for now; they get generated from the OpenAPI contract once
 * that exists (Phase 0 deliverable 4). Keep them in step with the schemas —
 * the console reads the public API and nothing else.
 */

/** Mirrors SubmissionStatus, i.e. submission_status_check in migration 0001. */
export const SUBMISSION_STATUSES = [
  "draft",
  "finalized",
  "in_review",
  "approved",
  "rejected",
  "correction_required",
] as const;

export type SubmissionStatus = (typeof SUBMISSION_STATUSES)[number];

export type OpKind =
  | "set"
  | "unset"
  | "repeat_add"
  | "repeat_delete"
  | "finalize"
  | "reopen";

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

export interface SubmissionListResponse {
  submissions: SubmissionSummary[];
  /** Total matching the filters, not the page. */
  total: number;
  limit: number;
  offset: number;
}

export interface SubmissionOpView {
  id: string;
  kind: OpKind;
  path: string | null;
  value: unknown;
  /** An encrypted op has a null `value` and carries the three fields below. */
  encrypted: boolean;
  /** Ciphertext, hex. Useless without a private key the server has never held —
   *  which is exactly why it is safe to hand over, and why decryption in this
   *  browser is possible at all (encryption envelope §7). */
  valueCiphertext: string | null;
  /** Which content key opens it: one per contributing device (§4.2). */
  contentKeyId: string | null;
  /** The nonce it was sealed under, hex. */
  nonce: string | null;
  deviceId: string;
  actorId: string | null;
  counter: number;
  /** Diagnostic only — ordering is (counter, deviceId). Sync spec §3. */
  wallClock: string;
  receivedAt: string;
  serverSeq: number;
}

export interface SubmissionStateView {
  data: Record<string, unknown>;
  opHighWater: number;
  computedAt: string;
}

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
  /** In (counter, deviceId) order — replay order, not arrival order. */
  ops: SubmissionOpView[];
  opsTruncated: boolean;
}

/** One content key wrapped to one recipient (encryption envelope §4.3). */
export interface WrappedKeyView {
  projectKeyId: string;
  ephemeralPublic: string;
  nonce: string;
  wrappedKey: string;
}

/** A submission's content key, in the only form the server has it: wrapped. */
export interface ContentKeyView {
  contentKeyId: string;
  deviceId: string;
  wraps: WrappedKeyView[];
}

export interface SubmissionKeysResponse {
  submissionId: string;
  /** One per contributing device. Decryption needs every one of them (§7). */
  contentKeys: ContentKeyView[];
}

export interface FormSummary {
  id: string;
  /** The wire form key, which is what a submission filter matches on. */
  formId: string;
  title: string;
  versions: number[];
  archivedAt: string | null;
}

export interface FormListResponse {
  forms: FormSummary[];
}

export interface Health {
  status: string;
  environment: string;
}

/** Mirrors project_security_mode_check in migration 0001. */
export const SECURITY_MODES = [
  "standard",
  "field_level",
  "project_e2e",
] as const;

export type SecurityMode = (typeof SECURITY_MODES)[number];

/** Mirrors project_key_role_check in migration 0001. */
export const KEY_ROLES = ["primary", "backup", "recovery"] as const;

export type KeyRole = (typeof KEY_ROLES)[number];

export interface ProjectSummary {
  id: string;
  name: string;
  slug: string;
  securityMode: SecurityMode;
  /** Recipients this project's submissions get wrapped to. Zero means devices
   *  in an encrypting mode cannot push at all. */
  activeKeyCount: number;
  createdAt: string;
  archivedAt: string | null;
}

export interface ProjectListResponse {
  projects: ProjectSummary[];
}

/** A recipient key. Public halves only — the console never holds a private key. */
export interface ProjectKeyDetail {
  keyId: string;
  projectId: string;
  /** Raw X25519 public key, 32 bytes, lowercase hex. */
  publicKey: string;
  role: KeyRole;
  label: string;
  createdAt: string;
  revokedAt: string | null;
}

export interface ProjectKeyListResponse {
  projectId: string;
  securityMode: SecurityMode;
  keys: ProjectKeyDetail[];
}

export interface ProjectKeyCreate {
  publicKey: string;
  role: KeyRole;
  label: string;
}
