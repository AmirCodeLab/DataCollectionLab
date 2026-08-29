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
  /** Ciphertext stays server-side; an encrypted op arrives with a null value. */
  encrypted: boolean;
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
