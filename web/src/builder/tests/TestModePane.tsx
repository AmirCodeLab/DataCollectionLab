/** Test mode (scope §4): the author's test cases, replayed after every edit.
 *
 * The regression half of the builder. RCons change questions the week before
 * fieldwork, and the risk in a late edit is never the question being edited —
 * it is the skip pattern four screens later that used to work. Each case is
 * run through the engine after every compile answer and on demand, and the
 * first failing expectation is shown as the engine reported it.
 *
 * The cases save with the draft. They are the author's, about this form, and
 * supposed to change when the form changes; they are not conformance vectors.
 */

import { useEffect, useMemo, useState } from "react";

import type { TestCase, TestStep } from "@/api/types";
import {
  loadEngine,
  type EngineModule,
  type PreviewState,
} from "@/builder/engine/facade";
import { usePreview } from "@/builder/preview/previewContext";
import { useBuilder } from "@/builder/store";
import { newCaseId, recordFromState, toTestStep } from "./record";
import { runCase, type CaseResult } from "./runner";

/** What the preview hands over when a case is recorded from it. */
export interface Recording {
  steps: TestStep[];
  state: PreviewState;
}

function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function TestModePane() {
  const ir = useBuilder((s) => s.ir);
  // A new case is the preview's walk so far: its recorded steps, and the
  // engine's state after them. The page's one session (previewContext.ts),
  // so what is recorded is exactly what the author has been looking at.
  const preview = usePreview();
  const recorder: (() => Recording | null) | undefined =
    preview === null
      ? undefined
      : () =>
          preview.status === "ready" && preview.state !== null
            ? { steps: preview.steps().map(toTestStep), state: preview.state }
            : null;
  const compileStatus = useBuilder((s) => s.compile.status);
  const testCases = useBuilder((s) => s.testCases);
  const addTestCase = useBuilder((s) => s.addTestCase);
  const removeTestCase = useBuilder((s) => s.removeTestCase);
  const renameTestCase = useBuilder((s) => s.renameTestCase);

  const [engine, setEngine] = useState<EngineModule | null>(null);
  const [engineError, setEngineError] = useState<string | null>(null);
  const [runNonce, setRunNonce] = useState(0);

  useEffect(() => {
    let cancelled = false;
    loadEngine().then(
      (mod) => {
        if (!cancelled) setEngine(mod);
      },
      (error: unknown) => {
        if (!cancelled) {
          setEngineError(
            error instanceof Error ? error.message : String(error),
          );
        }
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // Derived, not stored: the cases run against the document the server has
  // answered for. While the answer is stale the results are too, and say so,
  // rather than showing a verdict on a form that has since changed. "Run all"
  // re-runs the same document on demand.
  const results = useMemo<Record<string, CaseResult> | null>(() => {
    // The nonce is the \"Run all\" button: same inputs, run again.
    void runNonce;
    if (engine === null || ir === null || compileStatus !== "current")
      return null;
    const next: Record<string, CaseResult> = {};
    for (const testCase of testCases) {
      next[testCase.id] = runCase(engine, ir, todayIso(), testCase);
    }
    return next;
  }, [engine, ir, testCases, compileStatus, runNonce]);

  const runAll = () => setRunNonce((n) => n + 1);

  const record = () => {
    if (recorder === undefined) return;
    const recording = recorder();
    if (recording === null) return;
    const name = `Case ${String(testCases.length + 1)}`;
    const paths = Object.keys(recording.state.relevant);
    addTestCase(
      recordFromState(
        name,
        recording.steps,
        recording.state,
        paths,
        newCaseId(),
      ),
    );
  };

  return (
    <section
      className="mt-4 border-t border-slate-200 pt-3 text-xs"
      aria-label="test mode"
    >
      <div className="flex items-center gap-2">
        <h2 className="text-sm font-semibold text-slate-700">Test cases</h2>
        <span className="ms-auto flex items-center gap-2">
          {recorder !== undefined && (
            <button
              type="button"
              onClick={record}
              disabled={preview?.status !== "ready"}
              className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-50"
            >
              New from the preview's answers
            </button>
          )}
          <button
            type="button"
            onClick={runAll}
            disabled={engine === null || ir === null || testCases.length === 0}
            className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50 disabled:opacity-50"
          >
            Run all
          </button>
        </span>
      </div>
      {engineError !== null && (
        <p className="mt-1 text-amber-700" role="note">
          Not run: the engine is unavailable ({engineError}). Build it with
          scripts/build_engine_wasm.sh.
        </p>
      )}
      {testCases.length === 0 ? (
        <p className="mt-1 text-slate-500">
          No test cases yet. Walk the form in the preview, then save the answers
          as a case; it is replayed after every edit.
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {testCases.map((testCase) => (
            <CaseRow
              key={testCase.id}
              testCase={testCase}
              result={
                results?.[testCase.id] ??
                (engineError !== null
                  ? { outcome: "not-run", reason: "engine unavailable" }
                  : {
                      outcome: "not-run",
                      reason: "waiting for the server's answer",
                    })
              }
              onRename={(name) => renameTestCase(testCase.id, name)}
              onRemove={() => removeTestCase(testCase.id)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function CaseRow({
  testCase,
  result,
  onRename,
  onRemove,
}: {
  testCase: TestCase;
  result: CaseResult;
  onRename: (name: string) => void;
  onRemove: () => void;
}) {
  const steps = testCase.steps?.length ?? 0;
  const expectations = testCase.expectations?.length ?? 0;
  return (
    <li className="rounded border border-slate-200 p-2">
      <div className="flex items-center gap-2">
        <input
          aria-label={`name of ${testCase.id}`}
          value={testCase.name}
          onChange={(e) => onRename(e.target.value)}
          className="min-w-0 flex-1 rounded border border-transparent px-1 py-0.5 hover:border-slate-300 focus:border-slate-300"
        />
        <Outcome result={result} />
        <button
          type="button"
          aria-label={`remove ${testCase.name}`}
          onClick={onRemove}
          className="text-slate-400 hover:text-red-700"
        >
          ×
        </button>
      </div>
      <p className="mt-0.5 text-slate-500">
        {steps} step{steps === 1 ? "" : "s"} · {expectations} expectation
        {expectations === 1 ? "" : "s"}
      </p>
      {result.outcome === "fail" && (
        <p className="mt-0.5 text-red-700" role="alert">
          {result.reason}
        </p>
      )}
    </li>
  );
}

function Outcome({ result }: { result: CaseResult }) {
  switch (result.outcome) {
    case "pass":
      return <span className="text-green-700">pass</span>;
    case "fail":
      return <span className="text-red-700">fail</span>;
    case "not-run":
      return <span className="text-slate-500">not run: {result.reason}</span>;
  }
}
