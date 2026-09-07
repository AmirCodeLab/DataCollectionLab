/** Ask the server for a compile answer whenever the document changes.
 *
 * The page calls this once. It owns the debounce and reports through the
 * store's `compile*` actions, and it computes nothing itself: the screen
 * plan, the warnings and the refusals are `POST /forms/compile`'s answer for
 * the document as it was when asked. The store keeps that document by
 * identity (`askedFor`) so an answer that arrives after another edit is
 * marked stale rather than shown as current — the one honest thing to do
 * with a plan for a form the author no longer has (scope §3).
 *
 * One request in flight at a time. A change during a request is compiled
 * again as soon as the answer lands.
 */

import { useEffect, useRef } from "react";

import { ApiError } from "@/api/client";
import { compileForm } from "@/api/queries";
import { useBuilder } from "./store";

/** How long after the last edit a compile goes out. */
export const COMPILE_DEBOUNCE_MS = 600;

/** The §10 reasons out of a 422, verbatim. `PublishRefused` sends a list;
 *  `CompileError` sends one string. Neither is rephrased here. */
export function refusalsFrom(error: ApiError): string[] {
  const detail = error.detail;
  if (Array.isArray(detail)) return detail.map(String);
  if (typeof detail === "string") return [detail];
  return [error.message];
}

export function useAutoCompile(): void {
  const ir = useBuilder((s) => s.ir);
  const inFlight = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    if (ir === null) return;
    // A request is running; when it lands it looks again at the document.
    if (inFlight.current) return;

    const run = async (): Promise<void> => {
      const state = useBuilder.getState();
      const askedFor = state.ir;
      if (askedFor === null) return;
      inFlight.current = true;
      state.compileStarted(askedFor);
      try {
        const result = await compileForm(askedFor);
        if (mounted.current)
          useBuilder.getState().compileSucceeded(askedFor, result);
      } catch (error: unknown) {
        if (!mounted.current) return;
        if (error instanceof ApiError && error.status === 422) {
          useBuilder.getState().compileRefused(askedFor, refusalsFrom(error));
        } else {
          const message =
            error instanceof Error ? error.message : String(error);
          useBuilder.getState().compileFailed(askedFor, message);
        }
      } finally {
        inFlight.current = false;
        const after = useBuilder.getState();
        if (mounted.current && after.ir !== null && after.ir !== askedFor) {
          void run();
        }
      }
    };

    // The first answer for a document is wanted at once; edits are debounced.
    const delay =
      useBuilder.getState().compile.status === "idle" ? 0 : COMPILE_DEBOUNCE_MS;
    const handle = setTimeout(() => {
      void run();
    }, delay);
    return () => clearTimeout(handle);
  }, [ir]);
}
