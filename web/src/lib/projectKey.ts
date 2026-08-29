/** Project keypair generation, in the browser (encryption envelope §4.1).
 *
 * The private key is generated here, handed to the user as a file, and never
 * sent anywhere. Nothing in this module posts, fetches, or stores — it returns
 * the two halves and the caller decides what to do with each. That separation
 * is the point: a private key that never enters a request cannot leak from one.
 *
 * X25519 is not RSA and not P-256 (envelope §2): 32-byte keys, fast enough to
 * wrap per submission on a cheap Android handset, and identical on every
 * platform we run on.
 */

import type { KeyRole } from "@/api/types";

/** A freshly generated keypair. `privateKey` must be saved before anything else. */
export interface GeneratedKeypair {
  /** Raw X25519 public key, 32 bytes, lowercase hex — what gets uploaded. */
  publicKey: string;
  /** Raw X25519 private scalar, 32 bytes, lowercase hex — what gets downloaded. */
  privateKey: string;
}

export class KeygenUnsupportedError extends Error {
  constructor(detail: string) {
    super(
      `This browser cannot generate X25519 keys (${detail}). ` +
        "Use a current Chrome, Firefox or Safari — or generate the keypair " +
        "offline and register the public half.",
    );
    this.name = "KeygenUnsupportedError";
  }
}

function toHex(bytes: ArrayBuffer | Uint8Array): string {
  const view = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return Array.from(view, (b) => b.toString(16).padStart(2, "0")).join("");
}

/** Generate an X25519 keypair, returning both halves as raw hex.
 *
 * Browsers disagree about the algorithm name: the current spelling is
 * `X25519`, and older releases exposed the same curve through `ECDH`. Both are
 * tried rather than sniffing the user agent, which is wrong the day a browser
 * ships the newer one.
 */
export async function generateProjectKeypair(): Promise<GeneratedKeypair> {
  const subtle = globalThis.crypto?.subtle;
  if (subtle === undefined) {
    // Also what you get on plain http:// from another host — WebCrypto is only
    // exposed in a secure context.
    throw new KeygenUnsupportedError("WebCrypto is unavailable in this context");
  }

  const algorithms: Array<AlgorithmIdentifier | EcKeyGenParams> = [
    { name: "X25519" },
    { name: "ECDH", namedCurve: "X25519" } as EcKeyGenParams,
  ];

  let lastError = "no algorithm accepted";
  for (const algorithm of algorithms) {
    let pair: CryptoKeyPair;
    try {
      pair = (await subtle.generateKey(algorithm, true, [
        "deriveBits",
      ])) as CryptoKeyPair;
    } catch (cause) {
      lastError = String(cause);
      continue;
    }

    const publicKey = await subtle.exportKey("raw", pair.publicKey);
    // PKCS#8 wraps the 32-byte scalar in a 16-byte header. Exporting "raw" is
    // not permitted for private keys, so the scalar is taken from the tail —
    // and its length is checked rather than assumed, because a wrong 32 bytes
    // here is a keypair whose halves do not match and data nobody can open.
    const pkcs8 = new Uint8Array(await subtle.exportKey("pkcs8", pair.privateKey));
    if (pkcs8.length < 32) {
      throw new KeygenUnsupportedError(
        `private key export was ${pkcs8.length} bytes, expected at least 32`,
      );
    }
    const scalar = pkcs8.slice(pkcs8.length - 32);

    const generated = {
      publicKey: toHex(publicKey),
      privateKey: toHex(scalar),
    };
    await assertHalvesMatch(subtle, algorithm, generated, pair);
    return generated;
  }

  throw new KeygenUnsupportedError(lastError);
}

/** Prove the exported private half really opens what the public half seals.
 *
 * Cheap insurance against a browser whose PKCS#8 layout differs from the one
 * assumed above. Getting this wrong produces a keypair that looks perfectly
 * normal and silently cannot decrypt anything — discovered, at the earliest,
 * the day someone needs the data back.
 */
async function assertHalvesMatch(
  subtle: SubtleCrypto,
  algorithm: AlgorithmIdentifier | EcKeyGenParams,
  generated: GeneratedKeypair,
  pair: CryptoKeyPair,
): Promise<void> {
  const name = typeof algorithm === "string" ? algorithm : algorithm.name;
  const scalar = Uint8Array.from(
    generated.privateKey.match(/../g)!.map((byte) => parseInt(byte, 16)),
  );

  let reimported: CryptoKey;
  try {
    // Re-import through PKCS#8, the only private format WebCrypto accepts.
    // The header is fixed for X25519: version 0, AlgorithmIdentifier
    // 1.3.101.110 (06 03 2b 65 6e), then the scalar in an OCTET STRING.
    const pkcs8 = Uint8Array.from(
      ("302e020100300506032b656e04220420".match(/../g) ?? []).map((byte) =>
        parseInt(byte, 16),
      ),
    );
    const full = new Uint8Array(pkcs8.length + scalar.length);
    full.set(pkcs8);
    full.set(scalar, pkcs8.length);
    reimported = await subtle.importKey("pkcs8", full, algorithm, false, [
      "deriveBits",
    ]);
  } catch (cause) {
    throw new KeygenUnsupportedError(
      `the exported private key could not be re-imported (${String(cause)})`,
    );
  }

  const witness = (await subtle.generateKey(algorithm, true, [
    "deriveBits",
  ])) as CryptoKeyPair;

  const fromGenerated = await subtle.deriveBits(
    { name, public: witness.publicKey } as EcdhKeyDeriveParams,
    reimported,
    256,
  );
  const fromWitness = await subtle.deriveBits(
    { name, public: pair.publicKey } as EcdhKeyDeriveParams,
    witness.privateKey,
    256,
  );
  if (toHex(fromGenerated) !== toHex(fromWitness)) {
    throw new KeygenUnsupportedError(
      "the exported private key does not match the public key",
    );
  }
}

/** Short, stable identifier for a public key: the first 8 hex characters of its
 *  SHA-256 (envelope §4.1 keys are raw 32-byte X25519).
 *
 * It goes in the filename so a file can be matched to a key by looking at it,
 * without opening it and without the key id — which is what you need when you
 * are holding several files and the console is telling you the id of the one
 * that opens a submission. Truncated because a filename has to stay readable:
 * this identifies a key among a project's handful, it is not a security claim,
 * and nothing trusts it — `publicKey` inside the file is the authority.
 */
export async function publicKeyFingerprint(publicKeyHex: string): Promise<string> {
  const bytes = Uint8Array.from(
    publicKeyHex.match(/../g)!.map((byte) => parseInt(byte, 16)),
  );
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return toHex(digest).slice(0, 8);
}

/** What the downloaded file contains. Self-describing so it is still usable
 *  in two years by someone who was not there when it was made. */
export interface PrivateKeyFile {
  warning: string;
  format: string;
  spec: string;
  projectId: string;
  /** The `project_key` row this file's public half was registered as. Always
   *  set: the file is built after registration precisely so it can carry it. */
  keyId: string;
  role: KeyRole;
  label: string;
  createdAt: string;
  publicKey: string;
  privateKey: string;
}

export function privateKeyFileContents(
  keypair: GeneratedKeypair,
  meta: { projectId: string; keyId: string; role: KeyRole; label: string },
): PrivateKeyFile {
  return {
    warning:
      "SECRET. This private key is the ONLY way to read this project's " +
      "encrypted submissions. It was never sent to the server and cannot be " +
      "recovered, reset or reissued. If this file is lost, the data encrypted " +
      "to it is lost permanently. Store it the way you would store the data.",
    format:
      "X25519 raw private scalar, 32 bytes, lowercase hex (publicKey likewise)",
    spec: "specs/encryption-envelope-v0.1.md §4.1",
    projectId: meta.projectId,
    keyId: meta.keyId,
    role: meta.role,
    label: meta.label,
    createdAt: new Date().toISOString(),
    publicKey: keypair.publicKey,
    privateKey: keypair.privateKey,
  };
}

/** Hand the file to the user. Returns once the download has been triggered. */
export function downloadPrivateKey(file: PrivateKeyFile, filename: string): void {
  const blob = new Blob([JSON.stringify(file, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  // Give the browser a moment to start reading the blob before revoking it.
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export function privateKeyFilename(
  projectSlug: string,
  role: KeyRole,
  fingerprint: string,
): string {
  const stamp = new Date().toISOString().slice(0, 10);
  return `dcp-${projectSlug}-${role}-private-key-${stamp}-${fingerprint}.json`;
}
