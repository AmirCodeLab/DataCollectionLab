/** A real encrypted submission, built from the crypto conformance vectors.
 *
 * These tests do not invent ciphertext. `conformance/crypto` is the contract
 * the Python and Kotlin engines are both held to (docs/project-conventions.md rule 2), and the
 * browser is a third engine reading the same envelope — so it is held to the
 * same bytes. Two vectors line up for this by construction: `wrap-multi-001`
 * wraps content key 11181f26… to three recipients, and `op-value-001` encrypts
 * seven values under that same content key.
 *
 * The upshot is that a test asserting "Amina" appears on screen is asserting
 * the console decrypted bytes the reference implementation produced, not bytes
 * this file made up to match what the console happens to do.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";

import type {
  ProjectKeyDetail,
  SubmissionDetail,
  SubmissionKeysResponse,
  SubmissionOpView,
} from "@/api/types";

interface WrapCase {
  contentKey: string;
  contentKeyId: string;
  projectKeyId: string;
  recipientPublicKey: string;
  recipientPrivateKey: string;
  nonce: string;
  expected: { ephemeralPublic: string; wrappedKey: string };
}

interface OpValueCase {
  name: string;
  value: unknown;
  contentKey: string;
  opId: string;
  submissionId: string;
  path: string;
  formVersion: number;
  deviceId: string;
  counter: number;
  expected: { nonce: string; ciphertext: string };
}

// Read off the filesystem, not through an import. A `new URL(..., import.meta.url)`
// here gets rewritten by Vite into an asset reference and then refused for
// pointing outside the project root — and an import would need the vectors
// copied into web/, which is exactly how two copies of a contract drift apart.
// Vitest's cwd is web/, so the repo root is one level up.
const VECTOR_DIR = join(process.cwd(), "..", "conformance", "crypto");

function vector<T>(name: string): { cases: T[] } {
  return JSON.parse(readFileSync(join(VECTOR_DIR, `${name}.json`), "utf8")) as {
    cases: T[];
  };
}

const wraps = vector<WrapCase>("wrap-multi-001").cases;
const opValues = vector<OpValueCase>("op-value-001").cases;

const CONTENT_KEY_ID = wraps[0].contentKeyId;
const DEVICE_ID = opValues[0].deviceId;

const FORM_VERSION = opValues[0].formVersion;
const PRIMARY = wraps[0].projectKeyId;

export const SUBMISSION_ID = opValues[0].submissionId;
export const PROJECT_ID = "01J9TESTPROJECT00000000000";

/** The private half of the primary recipient — TEST ONLY, published in the
 *  vector file by design. This is the string that must never appear in
 *  storage or in a request. */
export const PRIVATE_KEY_HEX = wraps[0].recipientPrivateKey;

/** The file the console would have downloaded for the primary recipient. */
export const PRIVATE_KEY_FILE = JSON.stringify(
  {
    warning: "SECRET. TEST ONLY — this key is published in a conformance vector.",
    format: "X25519 raw private scalar, 32 bytes, lowercase hex",
    projectId: PROJECT_ID,
    keyId: PRIMARY,
    role: "primary",
    label: "Programme lead",
    publicKey: wraps[0].recipientPublicKey,
    privateKey: PRIVATE_KEY_HEX,
  },
  null,
  2,
);

/** The plaintext behind each op, keyed by path — what a correct decryption
 *  must produce, taken from the vector rather than restated here. */
const EXPECTED_ANSWERS: Record<string, unknown> = Object.fromEntries(
  opValues.map((c) => [c.path, c.value]),
);

/** Object keys, sorted — the envelope encrypts canonical JSON (§5.1), so a
 *  decrypted object comes back key-sorted whatever order the vector states it
 *  in. Comparing without this asserts the vector file's formatting. */
function canonical(value: unknown): unknown {
  if (value === null || typeof value !== "object") return value;
  if (Array.isArray(value)) return value.map(canonical);
  return Object.fromEntries(
    Object.keys(value)
      .sort()
      .map((k) => [k, canonical((value as Record<string, unknown>)[k])]),
  );
}

/** An answer as the console prints it. `formatValue` renders JSON — quoted
 *  strings and a literal `null`, so an empty answer cannot be confused with a
 *  missing one — which means the text on screen is `"Amina"`, with quotes. */
export const rendered = (path: string): string =>
  JSON.stringify(canonical(EXPECTED_ANSWERS[path]));

/** A distinctive plaintext that appears in no ciphertext, no id and no
 *  timestamp — so finding it on screen means decryption really happened. */
export const A_DECRYPTED_ANSWER = rendered("name");

function op(c: OpValueCase): SubmissionOpView {
  return {
    id: c.opId,
    kind: "set",
    path: c.path,
    value: null,
    encrypted: true,
    valueCiphertext: c.expected.ciphertext,
    contentKeyId: CONTENT_KEY_ID,
    nonce: c.expected.nonce,
    deviceId: c.deviceId,
    actorId: null,
    counter: c.counter,
    wallClock: "2026-08-30T09:15:00Z",
    receivedAt: "2026-08-30T09:20:00Z",
    serverSeq: c.counter + 1,
  };
}

export const submissionDetail: SubmissionDetail = {
  id: SUBMISSION_ID,
  projectId: PROJECT_ID,
  formId: "clinic_intake",
  formTitle: "Clinic intake",
  formVersion: FORM_VERSION,
  status: "finalized",
  originDeviceId: DEVICE_ID,
  createdBy: null,
  startedAt: "2026-08-30T09:00:00Z",
  finalizedAt: "2026-08-30T09:15:00Z",
  receivedAt: "2026-08-30T09:20:00Z",
  opCount: opValues.length,
  // Empty by design: the server folds what it can read, which is nothing here.
  state: { data: {}, opHighWater: opValues.length, computedAt: "2026-08-30T09:20:00Z" },
  ops: opValues.map(op),
  opsTruncated: false,
};

export const submissionKeys: SubmissionKeysResponse = {
  submissionId: SUBMISSION_ID,
  contentKeys: [
    {
      contentKeyId: CONTENT_KEY_ID,
      deviceId: DEVICE_ID,
      wraps: wraps.map((w) => ({
        projectKeyId: w.projectKeyId,
        ephemeralPublic: w.expected.ephemeralPublic,
        nonce: w.nonce,
        wrappedKey: w.expected.wrappedKey,
      })),
    },
  ],
};

export const projectKeys: ProjectKeyDetail[] = wraps.map((w, i) => ({
  keyId: w.projectKeyId,
  projectId: PROJECT_ID,
  publicKey: w.recipientPublicKey,
  role: (["primary", "backup", "recovery"] as const)[i],
  label: ["Programme lead", "Data manager", "Escrow"][i],
  createdAt: "2026-08-01T00:00:00Z",
  revokedAt: null,
}));
