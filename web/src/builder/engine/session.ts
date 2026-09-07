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

export interface PreviewHandle {
  status: PreviewStatus;
  /** Why the engine is unavailable, when it is. */
  error?: string;
  state: PreviewState | null;
  /** Run one operation on the session and show what the engine returned. */
  act: (fn: (session: PreviewSession) => PreviewState) => void;
  /** An answer, recorded so it survives the next reopen. */
  answer: (path: string, value: EngineValue) => void;
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
  /** Every answer the preview entered, in order, for replay on reopen. */
  const answers = useRef<{ path: string; value: EngineValue }[]>([]);

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
      const kept: { path: string; value: EngineValue }[] = [];
      for (const entry of answers.current) {
        try {
          latest = opened.set(entry.path, entry.value);
          kept.push(entry);
        } catch {
          // The path is no longer in the form; the answer goes with it.
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

  const answer = useCallback(
    (path: string, value: EngineValue) => {
      answers.current = [...answers.current, { path, value }];
      act((s) => s.set(path, value));
    },
    [act],
  );

  return { status, error, state, act, answer };
}
