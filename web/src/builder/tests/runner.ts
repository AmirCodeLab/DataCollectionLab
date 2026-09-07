/** Running an author's test case through the engine.
 *
 * The same engine the handset runs (facade.ts), opened fresh for each case:
 * the steps are applied in order, then every expectation is read against the
 * engine's final state. Nothing is evaluated here. A step the engine refuses
 * — a row it will not add, a path it does not have — fails the case with the
 * engine's own message, which is the diagnostic, not a rephrasing of it.
 */

import type { Expectation, TestCase, TestStep } from "@/api/types";
import {
  PreviewSession,
  type EngineModule,
  type EngineValue,
  type PreviewState,
} from "@/builder/engine/facade";

export type CaseResult =
  | { outcome: "pass" }
  | { outcome: "fail"; reason: string }
  | { outcome: "not-run"; reason: string };

export function runCase(
  engine: EngineModule,
  ir: unknown,
  today: string,
  testCase: TestCase,
): CaseResult {
  let session: PreviewSession;
  try {
    session = PreviewSession.open(engine, ir, today);
  } catch (error: unknown) {
    return { outcome: "fail", reason: message(error) };
  }
  try {
    let state = session.state();
    for (const step of testCase.steps ?? []) {
      try {
        state = applyStep(session, step);
      } catch (error: unknown) {
        return {
          outcome: "fail",
          reason: `step ${describe(step)}: ${message(error)}`,
        };
      }
    }
    for (const expectation of testCase.expectations ?? []) {
      const failed = check(expectation, state);
      if (failed !== null) return { outcome: "fail", reason: failed };
    }
    return { outcome: "pass" };
  } finally {
    session.close();
  }
}

function applyStep(session: PreviewSession, step: TestStep): PreviewState {
  switch (step.kind) {
    case "set":
      if (step.path === undefined || step.path === null) {
        throw new Error("a set step needs a path");
      }
      return session.set(step.path, (step.value ?? null) as EngineValue);
    case "addRow":
      if (!step.repeatId) throw new Error("an addRow step needs a repeat");
      return session.addRow(step.repeatId);
    case "deleteRow":
      if (!step.repeatId || !step.instanceId) {
        throw new Error("a deleteRow step needs a repeat and a row");
      }
      return session.deleteRow(step.repeatId, step.instanceId);
  }
}

/** The first thing the expectation says that the state does not, or null. */
export function check(
  expectation: Expectation,
  state: PreviewState,
): string | null {
  const path = expectation.path;
  if (!(path in state.relevant)) {
    return `\`${path}\` is not in the form`;
  }
  if (expectation.relevant !== undefined && expectation.relevant !== null) {
    const actual = state.relevant[path];
    if (actual !== expectation.relevant) {
      return `\`${path}\` expected ${expectation.relevant ? "relevant" : "hidden"}, was ${actual ? "relevant" : "hidden"}`;
    }
  }
  if (expectation.valid !== undefined && expectation.valid !== null) {
    const actual = state.valid[path];
    if (actual !== expectation.valid) {
      return `\`${path}\` expected ${expectation.valid ? "valid" : "invalid"}, was ${actual ? "valid" : "invalid"}`;
    }
  }
  if (expectation.checkValue) {
    const expected = JSON.stringify(expectation.value ?? null);
    const actual = JSON.stringify(state.values[path] ?? null);
    if (expected !== actual) {
      return `\`${path}\` expected ${expected}, was ${actual}`;
    }
  }
  return null;
}

function describe(step: TestStep): string {
  switch (step.kind) {
    case "set":
      return `set ${step.path ?? "?"}`;
    case "addRow":
      return `add a row to ${step.repeatId ?? "?"}`;
    case "deleteRow":
      return `delete ${step.repeatId ?? "?"}[${step.instanceId ?? "?"}]`;
  }
}

function message(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
