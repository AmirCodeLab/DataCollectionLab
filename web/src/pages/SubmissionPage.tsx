/** One submission: the folded current state, and the log it was folded from.
 *
 * Encrypted values are decrypted here in the browser, with a private key the
 * person at the keyboard loads from a file — never by the server, which has no
 * key, and never by anything that outlives this tab (encryption envelope §7).
 */

import { useEffect, useState, type ReactNode } from "react";
import { Link, getRouteApi } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import {
  REFRESH_INTERVAL_MS,
  projectKeysQuery,
  submissionKeysQuery,
  submissionQuery,
} from "@/api/queries";
import type { SubmissionOpView } from "@/api/types";
import { DecryptionPanel } from "@/components/DecryptionPanel";
import { RefreshControls, useAutoRefresh } from "@/components/RefreshControls";
import { StatusBadge } from "@/components/StatusBadge";
import { formatTimestamp, formatValue } from "@/lib/format";
import {
  decryptSubmission,
  parsePrivateKeyFile,
  type DecryptionResult,
  type OpDecryptionState,
} from "@/lib/decryptSubmission";
import { Td, Th } from "@/components/Table";

const route = getRouteApi("/submissions/$submissionId");

export function SubmissionPage() {
  const { submissionId } = route.useParams();
  const autoRefresh = useAutoRefresh((state) => state.enabled);

  const submission = useQuery({
    ...submissionQuery(submissionId),
    refetchInterval: autoRefresh ? REFRESH_INTERVAL_MS : false,
  });

  // The private key lives in component state and nowhere else: not in
  // react-query's cache, not in localStorage, not in the URL. Unmounting this
  // page is what forgets it.
  const [privateKey, setPrivateKey] = useState<{
    name: string;
    bytes: Uint8Array;
  } | null>(null);
  const [decryption, setDecryption] = useState<DecryptionResult | null>(null);
  const [decryptError, setDecryptError] = useState<string | null>(null);
  const [decrypting, setDecrypting] = useState(false);

  const projectId = submission.data?.projectId;
  const encrypted = submission.data?.ops.some((op) => op.encrypted) ?? false;

  // Only fetched once there is something encrypted to open: an unencrypted
  // submission has no wrapped keys and no reason to ask for any.
  const submissionKeys = useQuery({
    ...submissionKeysQuery(submissionId),
    enabled: encrypted,
  });
  // Revoked keys included: a wrap made before revocation is still a wrap, and
  // naming its holder is how someone finds the private key that opens it (§8).
  const projectKeys = useQuery({
    ...projectKeysQuery(projectId ?? "", true),
    enabled: encrypted && projectId !== undefined,
  });

  const detail = submission.data;
  const keysData = submissionKeys.data;
  const projectKeysData = projectKeys.data;

  useEffect(() => {
    if (privateKey === null || detail === undefined) {
      setDecryption(null);
      return;
    }
    if (keysData === undefined || projectKeysData === undefined) return;

    // A refetch replaces `detail`, so this re-runs and the decrypted view
    // follows new ops rather than going stale beside the log.
    let current = true;
    setDecrypting(true);
    decryptSubmission(detail, keysData, projectKeysData.keys, privateKey.bytes)
      .then((result) => {
        if (!current) return;
        setDecryption(result);
        setDecryptError(null);
      })
      .catch((cause: unknown) => {
        if (!current) return;
        setDecryption(null);
        setDecryptError(String(cause));
      })
      .finally(() => {
        if (current) setDecrypting(false);
      });
    return () => {
      current = false;
    };
  }, [privateKey, detail, keysData, projectKeysData]);

  const loadKeyFile = (file: File) => {
    void file
      .text()
      .then((contents) => {
        // Parse before storing: a file that is not a key should say so now,
        // not as a wall of failed decryptions.
        const bytes = parsePrivateKeyFile(contents);
        setDecryptError(null);
        setPrivateKey({ name: file.name, bytes });
      })
      .catch((cause: unknown) => {
        setPrivateKey(null);
        setDecryptError(`Could not read ${file.name}: ${String(cause)}`);
      });
  };

  const forgetKey = () => {
    // Overwrite the bytes rather than only dropping the reference: the array
    // may sit in the heap until the collector gets to it.
    privateKey?.bytes.fill(0);
    setPrivateKey(null);
    setDecryption(null);
    setDecryptError(null);
  };

  if (submission.isError) {
    return (
      <div>
        <BackLink />
        <p className="mt-4 text-red-600">
          Could not load {submissionId}: {String(submission.error)}
        </p>
      </div>
    );
  }
  if (detail === undefined) {
    return <p className="text-slate-500">Loading…</p>;
  }

  // With a key loaded this is the locally decrypted fold; without one it is the
  // server's, which by design holds nothing encrypted.
  const stateEntries = Object.entries(
    decryption?.answers ?? detail.state?.data ?? {},
  ).sort(([a], [b]) => a.localeCompare(b));

  return (
    <section>
      <BackLink />

      <div className="mt-2 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="font-mono text-xl font-semibold">{detail.id}</h1>
          <p className="mt-1 text-sm text-slate-600">
            {detail.formTitle}{" "}
            <span className="text-slate-500">
              ({detail.formId} v{detail.formVersion})
            </span>
          </p>
        </div>
        <RefreshControls
          isFetching={submission.isFetching}
          updatedAt={submission.dataUpdatedAt}
          onRefresh={() => void submission.refetch()}
        />
      </div>

      <dl className="mt-4 grid grid-cols-2 gap-x-8 gap-y-2 text-sm sm:grid-cols-4">
        <Fact label="Status">
          <StatusBadge status={detail.status} />
        </Fact>
        <Fact label="Origin device">
          <span className="font-mono text-xs">
            {detail.originDeviceId ?? "—"}
          </span>
        </Fact>
        <Fact label="Ops">{detail.opCount}</Fact>
        <Fact label="Received">{formatTimestamp(detail.receivedAt)}</Fact>
        <Fact label="Started">{formatTimestamp(detail.startedAt)}</Fact>
        <Fact label="Finalized">{formatTimestamp(detail.finalizedAt)}</Fact>
        <Fact label="Created by">{detail.createdBy ?? "—"}</Fact>
        <Fact label="Project">
          <span className="font-mono text-xs">{detail.projectId}</span>
        </Fact>
      </dl>

      {encrypted && (
        <DecryptionPanel
          encryptedOps={detail.ops.filter((op) => op.encrypted).length}
          totalOps={detail.ops.length}
          keyName={privateKey?.name ?? null}
          busy={decrypting}
          error={decryptError}
          result={decryption}
          onLoadFile={loadKeyFile}
          onForget={forgetKey}
        />
      )}

      <h2 className="mt-8 text-lg font-semibold">
        Current state
        {decryption !== null && (
          <span className="ms-2 rounded bg-emerald-100 px-2 py-0.5 align-middle text-xs font-medium text-emerald-900">
            decrypted in this browser
          </span>
        )}
      </h2>
      <p className="text-sm text-slate-600">
        {decryption === null ? (
          <>
            The server&apos;s fold of the log below, last computed{" "}
            {formatTimestamp(detail.state?.computedAt ?? null)}. Encrypted
            answers are absent from it: the server cannot read them, so they have
            no place in a queryable projection.
          </>
        ) : (
          <>
            Folded in this browser from the log below, with the private key you
            loaded. Nothing here was computed on the server.
          </>
        )}
      </p>
      {stateEntries.length === 0 ? (
        <p className="mt-3 text-slate-500">No values yet.</p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[32rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-slate-600">
                <Th>Path</Th>
                <Th>Value</Th>
              </tr>
            </thead>
            <tbody>
              {stateEntries.map(([path, value]) => (
                <tr key={path} className="border-b border-slate-100">
                  <Td className="font-mono text-xs">{path}</Td>
                  <Td className="font-mono text-xs">{formatValue(value)}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <h2 className="mt-8 text-lg font-semibold">Op log</h2>
      <p className="text-sm text-slate-600">
        In (counter, deviceId) order — the order the fold replays in. Wall
        clocks are diagnostic and never order anything.
      </p>
      {detail.opsTruncated && (
        <p className="mt-2 text-sm text-amber-700">
          Showing the first {detail.ops.length} of {detail.opCount} ops.
        </p>
      )}
      <div className="mt-3 overflow-x-auto">
        <table className="w-full min-w-[56rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-slate-600">
              <Th className="text-end">#</Th>
              <Th className="text-end">Counter</Th>
              <Th>Device</Th>
              <Th>Kind</Th>
              <Th>Path</Th>
              <Th>Value</Th>
              <Th>Wall clock</Th>
              <Th>Received</Th>
            </tr>
          </thead>
          <tbody>
            {detail.ops.map((op, index) => (
              <tr key={op.id} className="border-b border-slate-100">
                <Td className="text-end tabular-nums text-slate-500">
                  {index + 1}
                </Td>
                <Td className="text-end tabular-nums">{op.counter}</Td>
                <Td className="font-mono text-xs">{op.deviceId}</Td>
                <Td>
                  <code>{op.kind}</code>
                </Td>
                <Td className="font-mono text-xs">{op.path ?? "—"}</Td>
                <Td className="font-mono text-xs">
                  <OpValue op={op} decrypted={decryption?.values[op.id]} />
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {formatTimestamp(op.wallClock)}
                </Td>
                <Td className="whitespace-nowrap text-xs">
                  {formatTimestamp(op.receivedAt)}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {detail.ops.length === 0 && (
        <p className="py-6 text-slate-500">This submission has no ops.</p>
      )}
    </section>
  );
}

function OpValue({
  op,
  decrypted,
}: {
  op: SubmissionOpView;
  decrypted?: { state: OpDecryptionState; value: unknown };
}) {
  if (!op.encrypted) {
    return <>{formatValue(op.value)}</>;
  }
  // Without a loaded key the console holds nothing that opens this, by design
  // (encryption envelope §3) — and neither does the server.
  if (decrypted === undefined || decrypted.state === "no-key") {
    return <span className="text-slate-500">encrypted</span>;
  }
  if (decrypted.state === "failed") {
    // These bytes are not the ones sealed for this op at this path: corruption,
    // or someone moved a ciphertext. Never shown as a value.
    return <span className="text-red-700">failed to authenticate</span>;
  }
  return (
    <span className="rounded bg-emerald-100 px-1 text-emerald-900" title="Decrypted in this browser">
      {formatValue(decrypted.value)}
    </span>
  );
}

function BackLink() {
  return (
    <Link
      to="/submissions"
      className="text-sm text-blue-700 hover:underline"
    >
      ← All submissions
    </Link>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-500">
        {label}
      </dt>
      <dd className="mt-0.5">{children}</dd>
    </div>
  );
}
