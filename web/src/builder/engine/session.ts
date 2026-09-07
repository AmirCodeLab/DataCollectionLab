/** One open form in the browser engine, following the document as it changes.
 *
 * The session is the engine's — every relevance, value, count and blocker the
 * preview shows is read out of the `PreviewState` the engine returns. What
 * this hook adds is only the lifecycle: load the module once, open a session
 * for the current document, and when the document changes (the store swaps
 * the object on every edit) open a fresh session and replay the answers the
 * preview had entered so far. Replaying, rather than keeping the old session,
 * is what makes the preview honest after an edit: the engine compiled the new
 * document, and the answers were re-applied to it, so a path the edit removed
 * is dropped — the engine reports the error and the answer is forgotten.
 *
 * "Answers" means every step that changes the form's data, not only `set`:
 * a row the author added in the preview is data too (§11.3), and a preview
 * that forgot it on every edit — and with it every answer inside it — would
 * be the blank roster one more time. The recorded steps are also what a test
 * case is made from (scope §4, test mode).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { FormIr } from "@/builder/ir";
import {
  loadEngine,
  PreviewSession,
  type EngineModule,
  type EngineValue,
  type PreviewState,
} from "./facade";

export type PreviewStatus = "loading" | "ready" | "unavailable";

/** One data-changing step the preview took, in the order it took them. */
export type PreviewStep =
  | { kind: "set"; path: string; value: EngineValue }
  | { kind: "addRow"; repeatId: string }
  | { kind: "deleteRow"; repeatId: string; instanceId: string };

function replay(session: PreviewSession, step: PreviewStep): PreviewState {
  switch (step.kind) {
    case "set":
      return session.set(step.path, step.value);
    case "addRow":
      return session.addRow(step.repeatId);
    case "deleteRow":
      return session.deleteRow(step.repeatId, step.instanceId);
  }
}

export interface PreviewHandle {
  status: PreviewStatus;
  /** Why the engine is unavailable, when it is. */
  error?: string;
  state: PreviewState | null;
  /** Run one operation on the session and show what the engine returned. */
  act: (fn: (session: PreviewSession) => PreviewState) => void;
  /** An answer, recorded so it survives the next reopen. */
  answer: (path: string, value: EngineValue) => void;
  /** A row added, recorded likewise (§11.3: the new row is entered). */
  addRow: (repeatId: string) => void;
  /** A row deleted, recorded likewise. */
  deleteRow: (repeatId: string, instanceId: string) => void;
  /** Every data-changing step so far, for replay and for recording a test case. */
  steps: () => PreviewStep[];
}

export const ENGINE_UNAVAILABLE =
  "The engine bundle is not built. Run scripts/build_engine_wasm.sh.";

/** Today's date as the engine wants it. */
export function todayIso(): string {
  return new Date().toISOString().slice(0, 10);
}

export function usePreviewSession(
  ir: FormIr | null,
  today: string,
): PreviewHandle {
  const [engine, setEngine] = useState<EngineModule | null>(null);
  const [status, setStatus] = useState<PreviewStatus>("loading");
  const [error, setError] = useState<string | undefined>(undefined);
  const [state, setState] = useState<PreviewState | null>(null);
  const session = useRef<PreviewSession | null>(null);
  /** Every data-changing step the preview took, in order, for replay on reopen. */
  const answers = useRef<PreviewStep[]>([]);

  useEffect(() => {
    let cancelled = false;
    loadEngine().then(
      (mod) => {
        if (cancelled) return;
        setEngine(mod);
      },
      (cause: unknown) => {
        if (cancelled) return;
        setStatus("unavailable");
        setError(
          `${ENGINE_UNAVAILABLE} (${cause instanceof Error ? cause.message : String(cause)})`,
        );
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // Open a session for this document, replaying the answers so far. The old
  // session is closed first: the engine holds it, and a handle nobody can
  // reach is a leak the console would never notice. Opening is deferred a
  // tick so the effect itself sets no state (react-hooks/set-state-in-effect).
  useEffect(() => {
    if (engine === null || ir === null) return;
    let cancelled = false;
    let opened: PreviewSession | null = null;
    void Promise.resolve().then(() => {
      if (cancelled) return;
      session.current?.close();
      session.current = null;
      try {
        opened = PreviewSession.open(engine, ir, today);
      } catch (cause: unknown) {
        setStatus("unavailable");
        setError(cause instanceof Error ? cause.message : String(cause));
        setState(null);
        return;
      }
      let latest = opened.state();
      const kept: PreviewStep[] = [];
      for (const entry of answers.current) {
        try {
          latest = replay(opened, entry);
          kept.push(entry);
        } catch {
          // The path or the repeat is no longer in the form; the step goes
          // with it, and so does everything that depended on it.
        }
      }
      answers.current = kept;
      session.current = opened;
      setState(latest);
      setStatus("ready");
      setError(undefined);
    });
    return () => {
      cancelled = true;
      if (opened !== null) {
        opened.close();
        if (session.current === opened) session.current = null;
      }
    };
  }, [engine, ir, today]);

  const act = useCallback((fn: (s: PreviewSession) => PreviewState) => {
    const current = session.current;
    if (current === null) return;
    try {
      setState(fn(current));
    } catch (cause: unknown) {
      // A refused operation leaves the position where it was (§11.3); the
      // engine's message is the whole explanation, so it is shown as is.
      setError(cause instanceof Error ? cause.message : String(cause));
      setState(current.state());
    }
  }, []);

  /** Run a step and, if the engine took it, remember it for replay. */
  const record = useCallback((step: PreviewStep) => {
    const current = session.current;
    if (current === null) return;
    try {
      setState(replay(current, step));
      answers.current = [...answers.current, step];
    } catch (cause: unknown) {
      // Refused (§2.3, §11.3): not recorded, position unchanged, message shown.
      setError(cause instanceof Error ? cause.message : String(cause));
      setState(current.state());
    }
  }, []);
  const answer = useCallback(
    (path: string, value: EngineValue) => record({ kind: "set", path, value }),
    [record],
  );
  const addRow = useCallback(
    (repeatId: string) => record({ kind: "addRow", repeatId }),
    [record],
  );
  const deleteRow = useCallback(
    (repeatId: string, instanceId: string) =>
      record({ kind: "deleteRow", repeatId, instanceId }),
    [record],
  );
  const steps = useCallback(() => answers.current, []);

  return { status, error, state, act, answer, addRow, deleteRow, steps };
}
