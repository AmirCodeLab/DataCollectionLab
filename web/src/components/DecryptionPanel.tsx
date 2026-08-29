/** Load a private key and decrypt a submission, in this browser only.
 *
 * The panel is deliberately loud about where the work happens. A console that
 * quietly showed plaintext would be indistinguishable, on screen, from a server
 * that had kept a copy of everyone's answers — and the whole point of
 * `project_e2e` is that it did not. So the page says which key opened what,
 * where the key is, and what will make it disappear.
 */

import type { ChangeEvent } from "react";

import type { DecryptionResult } from "@/lib/decryptSubmission";

interface Props {
  /** How many ops on this submission are encrypted, of how many in total. */
  encryptedOps: number;
  totalOps: number;
  /** The name of the file the key came from. Never the key itself. */
  keyName: string | null;
  busy: boolean;
  error: string | null;
  result: DecryptionResult | null;
  onLoadFile: (file: File) => void;
  onForget: () => void;
}

export function DecryptionPanel({
  encryptedOps,
  totalOps,
  keyName,
  busy,
  error,
  result,
  onLoadFile,
  onForget,
}: Props) {
  const active = keyName !== null;

  const pick = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Clear the input so picking the same file twice still fires a change.
    event.target.value = "";
    if (file) onLoadFile(file);
  };

  return (
    <section
      className={`mt-8 rounded border px-4 py-3 ${
        active ? "border-emerald-400 bg-emerald-50" : "border-slate-300 bg-slate-50"
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">
            {active ? "Decrypted in this browser" : "Decrypt locally"}
          </h2>
          <p className="mt-1 text-sm text-slate-700">
            {encryptedOps} of {totalOps} operations are encrypted. The server
            stores them as ciphertext and holds no key that opens them.
          </p>
        </div>
        {active && (
          <button
            type="button"
            onClick={onForget}
            className="rounded border border-slate-400 bg-white px-3 py-1.5 text-sm font-medium"
          >
            Forget key
          </button>
        )}
      </div>

      {!active && (
        <div className="mt-3">
          <label className="block text-sm font-medium" htmlFor="private-key">
            Private key file
          </label>
          <input
            id="private-key"
            type="file"
            accept=".json,.txt,application/json,text/plain"
            onChange={pick}
            className="mt-1 block text-sm"
          />
          <p className="mt-2 max-w-2xl text-xs text-slate-600">
            The file this console downloaded when the keypair was generated, or
            a bare 32-byte hex scalar. It is read in this tab, kept in memory
            for as long as the page is open, and{" "}
            <strong>never uploaded, never stored and never logged</strong>.
            Reloading or leaving this page forgets it.
          </p>
        </div>
      )}

      {active && (
        <p className="mt-2 text-sm text-emerald-900">
          Key loaded from <span className="font-mono text-xs">{keyName}</span>.
          It is held in this tab&apos;s memory only — nothing was sent to the
          server, and a reload forgets it.
        </p>
      )}

      {busy && <p className="mt-3 text-sm text-slate-600">Decrypting…</p>}

      {error !== null && (
        <p className="mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-sm text-red-900">
          {error}
        </p>
      )}

      {result !== null && (
        <>
          <p className="mt-3 text-sm text-slate-700">
            Opened {result.contentKeys.filter((key) => key.opened).length} of{" "}
            {result.contentKeys.length} content keys · decrypted{" "}
            {result.decryptedOps} of {result.encryptedOps} encrypted values.
          </p>

          {result.contentKeys.length > 0 && (
            <ul className="mt-2 space-y-1 text-xs">
              {result.contentKeys.map((key) => (
                <li key={key.contentKeyId}>
                  <span
                    className={
                      key.opened
                        ? "font-medium text-emerald-800"
                        : "font-medium text-amber-800"
                    }
                  >
                    {key.opened ? "opened" : "not opened"}
                  </span>{" "}
                  <span className="font-mono">{key.contentKeyId}</span> — device{" "}
                  <span className="font-mono">{key.deviceId}</span>, wrapped to{" "}
                  {key.wrappedTo.join("; ")}
                </li>
              ))}
            </ul>
          )}

          {result.problems.map((problem) => (
            <p
              key={problem}
              className="mt-2 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900"
            >
              {problem}
            </p>
          ))}
        </>
      )}
    </section>
  );
}
