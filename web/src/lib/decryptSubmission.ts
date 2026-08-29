/** Decryption in the browser (encryption envelope §7).
 *
 * The private key is loaded from a file the user picks, lives in this tab's
 * memory for as long as the page is open, and is never uploaded, never written
 * to localStorage, never put in a URL and never handed to react-query — a
 * cached query key is a copy of the key, and a copy is a leak waiting for
 * someone's devtools export.
 *
 * Every step mirrors backend/app/modules/crypto/envelope.py, which is the
 * reference implementation. Where the two disagree, that file is right and
 * this one is broken.
 *
 * Nothing here fetches: the caller passes in what the API returned and gets
 * back plaintext. That separation is the same one that keeps
 * lib/projectKey.ts honest — a module with no network access cannot exfiltrate
 * what it holds.
 */

import type {
  ProjectKeyDetail,
  SubmissionDetail,
  SubmissionKeysResponse,
  SubmissionOpView,
} from "@/api/types";

/** Envelope §4.4 and §4.5 — the strings that go into HKDF and the AAD. */
const WRAP_INFO = "dcp/v1/wrap";

const encoder = new TextEncoder();
const decoder = new TextDecoder();

export class PrivateKeyFileError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "PrivateKeyFileError";
  }
}

/** WebCrypto takes a BufferSource backed by a plain ArrayBuffer, never a shared
 *  one, and TypeScript now distinguishes the two. Every byte array here is
 *  built over its own buffer so it satisfies that without a cast. */
type Bytes = Uint8Array<ArrayBuffer>;

function fromHex(hex: string): Bytes {
  const clean = hex.trim().toLowerCase();
  if (clean.length % 2 !== 0 || /[^0-9a-f]/.test(clean)) {
    throw new PrivateKeyFileError("expected lowercase hex");
  }
  const bytes = new Uint8Array(new ArrayBuffer(clean.length / 2));
  for (let i = 0; i < bytes.length; i += 1) {
    bytes[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  }
  return bytes;
}

/** Read a private key out of the file the console downloaded, or bare hex.
 *
 * Deliberately tolerant about the container and strict about the key: a
 * 31-byte scalar accepted here becomes "this key opens nothing" three screens
 * later, with no clue why.
 */
export function parsePrivateKeyFile(contents: string): Bytes {
  const trimmed = contents.trim();
  let hex = trimmed;
  if (trimmed.startsWith("{")) {
    let document: unknown;
    try {
      document = JSON.parse(trimmed);
    } catch {
      throw new PrivateKeyFileError("that file looks like JSON but does not parse");
    }
    const value =
      document && typeof document === "object"
        ? (document as Record<string, unknown>).privateKey
        : undefined;
    if (typeof value !== "string") {
      throw new PrivateKeyFileError(
        "no `privateKey` field — expected the key file this console downloaded " +
          "when the keypair was generated",
      );
    }
    hex = value;
  }

  const scalar = fromHex(hex.replace(/\s+/g, ""));
  if (scalar.length !== 32) {
    throw new PrivateKeyFileError(
      `a private key is 32 bytes; this file holds ${scalar.length}`,
    );
  }
  return scalar;
}

/** PKCS#8 prefix for an X25519 private key: version 0, OID 1.3.101.110,
 *  then the scalar in an OCTET STRING. WebCrypto imports no other format. */
const PKCS8_PREFIX = fromHex("302e020100300506032b656e04220420");

/** Browsers disagree on the name; try both rather than sniff the user agent. */
const ALGORITHMS: Array<AlgorithmIdentifier | EcKeyGenParams> = [
  { name: "X25519" },
  { name: "ECDH", namedCurve: "X25519" } as EcKeyGenParams,
];

interface ImportedKey {
  key: CryptoKey;
  algorithm: AlgorithmIdentifier | EcKeyGenParams;
}

async function importPrivateKey(
  subtle: SubtleCrypto,
  scalar: Uint8Array,
): Promise<ImportedKey> {
  const pkcs8 = new Uint8Array(new ArrayBuffer(PKCS8_PREFIX.length + scalar.length));
  pkcs8.set(PKCS8_PREFIX);
  pkcs8.set(scalar, PKCS8_PREFIX.length);

  let lastError = "no algorithm accepted";
  for (const algorithm of ALGORITHMS) {
    try {
      const key = await subtle.importKey("pkcs8", pkcs8, algorithm, false, [
        "deriveBits",
      ]);
      return { key, algorithm };
    } catch (cause) {
      lastError = String(cause);
    }
  }
  throw new PrivateKeyFileError(
    `this browser cannot import X25519 private keys (${lastError}). Use a ` +
      "current Chrome, Firefox or Safari, or decrypt with " +
      "scripts/decrypt_submission.py.",
  );
}

/** Envelope §4.4, in reverse: X25519 → HKDF-SHA256 → AES-GCM.
 *
 * The HKDF salt is the RECIPIENT's public key — ours, when the wrap is
 * addressed to us. We cannot derive it from the scalar (WebCrypto exposes no
 * scalar multiplication), so it comes from the project key the wrap names, and
 * a wrap addressed to somebody else simply fails to authenticate. That failure
 * is the test: AES-GCM either verifies or it does not, and no amount of
 * matching key ids would be better evidence.
 */
async function unwrapContentKey(
  subtle: SubtleCrypto,
  imported: ImportedKey,
  contentKeyId: string,
  projectKeyId: string,
  recipientPublic: Bytes,
  wrap: { ephemeralPublic: string; nonce: string; wrappedKey: string },
): Promise<Bytes> {
  const name =
    typeof imported.algorithm === "string" ? imported.algorithm : imported.algorithm.name;

  const ephemeral = await subtle.importKey(
    "raw",
    fromHex(wrap.ephemeralPublic),
    imported.algorithm,
    false,
    [],
  );
  const shared = await subtle.deriveBits(
    { name, public: ephemeral } as EcdhKeyDeriveParams,
    imported.key,
    256,
  );

  const hkdf = await subtle.importKey("raw", shared, "HKDF", false, ["deriveBits"]);
  const wrappingKey = await subtle.deriveBits(
    {
      name: "HKDF",
      hash: "SHA-256",
      salt: recipientPublic,
      info: encoder.encode(WRAP_INFO + contentKeyId),
    },
    hkdf,
    256,
  );

  const aesKey = await subtle.importKey("raw", wrappingKey, "AES-GCM", false, [
    "decrypt",
  ]);
  const opened = await subtle.decrypt(
    {
      name: "AES-GCM",
      iv: fromHex(wrap.nonce),
      additionalData: encoder.encode(projectKeyId + contentKeyId),
      tagLength: 128,
    },
    aesKey,
    fromHex(wrap.wrappedKey),
  );
  return new Uint8Array(opened);
}

/** Envelope §5: the AAD binds a value to its exact location.
 *
 * Without it a server operator could move an encrypted answer from `income` to
 * `age`, or replay it against a form version where the path means something
 * else, and decryption would succeed without complaint.
 */
function opAad(op: SubmissionOpView, submissionId: string, formVersion: number): Bytes {
  return encoder.encode(
    [op.id, submissionId, op.path ?? "", String(formVersion)].join("|"),
  );
}

async function decryptOpValue(
  subtle: SubtleCrypto,
  op: SubmissionOpView,
  contentKey: Bytes,
  submissionId: string,
  formVersion: number,
): Promise<unknown> {
  const key = await subtle.importKey("raw", contentKey, "AES-GCM", false, ["decrypt"]);
  const plaintext = await subtle.decrypt(
    {
      name: "AES-GCM",
      iv: fromHex(op.nonce!),
      additionalData: opAad(op, submissionId, formVersion),
      tagLength: 128,
    },
    key,
    fromHex(op.valueCiphertext!),
  );
  // Canonical JSON on the way in (§5.1), so plain JSON on the way out.
  return JSON.parse(decoder.decode(plaintext)) as unknown;
}

export type OpDecryptionState = "plaintext" | "decrypted" | "no-key" | "failed";

export interface ContentKeyStatus {
  contentKeyId: string;
  deviceId: string;
  opened: boolean;
  /** The recipients this content key was wrapped to, as the console names them. */
  wrappedTo: string[];
}

export interface DecryptionResult {
  /** The fold, in (counter, deviceId) order — the same one the server runs. */
  answers: Record<string, unknown>;
  /** Per-op outcome, keyed by op id, for the log table. */
  values: Record<string, { state: OpDecryptionState; value: unknown }>;
  contentKeys: ContentKeyStatus[];
  /** Prose for the panel: what did not open, and why that is not a bug. */
  problems: string[];
  decryptedOps: number;
  encryptedOps: number;
}

/** Unwrap what this key opens, decrypt what it covers, fold the result.
 *
 * A submission built by several devices has one content key per device (§4.2)
 * and needs all of them. One this key cannot open is reported rather than
 * skipped: "no answers" and "no answers you hold the key for" are different
 * facts, and only one of them is a bug.
 */
export async function decryptSubmission(
  detail: SubmissionDetail,
  keys: SubmissionKeysResponse,
  projectKeys: ProjectKeyDetail[],
  privateKey: Uint8Array,
): Promise<DecryptionResult> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined) {
    // Also what you get on plain http:// from another host: WebCrypto is only
    // exposed in a secure context.
    throw new PrivateKeyFileError(
      "WebCrypto is unavailable in this context, so nothing can be decrypted here",
    );
  }

  const imported = await importPrivateKey(subtle, privateKey);
  const publicByKeyId = new Map(projectKeys.map((key) => [key.keyId, key.publicKey]));
  const describe = (keyId: string): string => {
    const key = projectKeys.find((candidate) => candidate.keyId === keyId);
    if (key === undefined) return `${keyId} (not a key of this project)`;
    return `${key.role} — ${key.label}${key.revokedAt === null ? "" : " (revoked)"}`;
  };

  const contentKeys: ContentKeyStatus[] = [];
  const opened = new Map<string, Bytes>();
  const problems: string[] = [];

  for (const contentKey of keys.contentKeys) {
    let material: Bytes | null = null;
    for (const wrap of contentKey.wraps) {
      const recipientPublic = publicByKeyId.get(wrap.projectKeyId);
      if (recipientPublic === undefined) continue;
      try {
        material = await unwrapContentKey(
          subtle,
          imported,
          contentKey.contentKeyId,
          wrap.projectKeyId,
          fromHex(recipientPublic),
          wrap,
        );
        break;
      } catch {
        // Addressed to another recipient. Expected — every content key carries
        // one wrap per recipient and this key is at most one of them.
      }
    }

    const wrappedTo = contentKey.wraps.map((wrap) => describe(wrap.projectKeyId));
    contentKeys.push({
      contentKeyId: contentKey.contentKeyId,
      deviceId: contentKey.deviceId,
      opened: material !== null,
      wrappedTo,
    });
    if (material === null) {
      problems.push(
        `The content key for device ${contentKey.deviceId} is not wrapped to this ` +
          `private key. It is wrapped to: ${wrappedTo.join("; ")}. A key registered ` +
          "after a submission was encrypted opens nothing older — historical " +
          "submissions are never re-wrapped (envelope §8).",
      );
    } else {
      opened.set(contentKey.contentKeyId, material);
    }
  }

  const values: DecryptionResult["values"] = {};
  let answers: Record<string, unknown> = {};
  let decryptedOps = 0;
  let encryptedOps = 0;

  // The fold of sync protocol §6: last writer wins by (counter, deviceId),
  // never by wall clock. Same order as the server's own fold, so this view and
  // every other view of the submission agree.
  const ordered = [...detail.ops].sort(
    (a, b) => a.counter - b.counter || a.deviceId.localeCompare(b.deviceId),
  );

  for (const op of ordered) {
    let state: OpDecryptionState = "plaintext";
    let value: unknown = op.value;

    if (op.encrypted) {
      encryptedOps += 1;
      const material =
        op.contentKeyId === null ? undefined : opened.get(op.contentKeyId);
      if (material === undefined) {
        state = "no-key";
      } else {
        try {
          value = await decryptOpValue(subtle, op, material, detail.id, detail.formVersion);
          state = "decrypted";
          decryptedOps += 1;
        } catch (cause) {
          // Not noise: these bytes are not the ones sealed for this op, at this
          // path, in this form version. Corruption, or tampering.
          state = "failed";
          problems.push(
            `Op ${op.id} (${op.path ?? "—"}) did not authenticate: ${String(cause)}`,
          );
        }
      }
    }

    values[op.id] = { state, value };
    if (state === "failed" || state === "no-key") continue;

    const path = op.path;
    if (op.kind === "set" && path !== null) {
      answers[path] = value;
    } else if (op.kind === "unset" && path !== null) {
      delete answers[path];
    } else if (op.kind === "repeat_delete" && path !== null) {
      const dot = `${path}.`;
      const bracket = `${path}[`;
      answers = Object.fromEntries(
        Object.entries(answers).filter(
          ([key]) => key !== path && !key.startsWith(dot) && !key.startsWith(bracket),
        ),
      );
    }
  }

  if (detail.opsTruncated) {
    problems.push(
      `Only the first ${detail.ops.length} of ${detail.opCount} ops were returned, ` +
        "so these answers are a prefix of the log rather than its current state.",
    );
  }

  return { answers, values, contentKeys, problems, decryptedOps, encryptedOps };
}
