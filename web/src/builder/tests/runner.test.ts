/** The runner asks the engine and reads its answer; it decides nothing. */

import { describe, expect, it } from "vitest";

import type { TestCase } from "@/api/types";
import type { EngineModule, PreviewState } from "@/builder/engine/facade";
import { check, runCase } from "./runner";

function stateWith(overrides: Partial<PreviewState>): PreviewState {
  return {
    screen: null,
    inside: null,
    progress: [1, 1],
    hasNext: false,
    hasPrevious: false,
    questions: [],
    roster: null,
    canFinalize: true,
    blockers: [],
    values: { consent: null, page_q: null, total: 7 },
    relevant: { consent: true, page_q: true, total: true },
    valid: { consent: true, page_q: true, total: true },
    ...overrides,
  };
}

/** A fake engine: `set consent=no` hides page_q; adding a row to `visits` is refused. */
function fakeEngine(): EngineModule & { calls: string[] } {
  let state = stateWith({});
  const calls: string[] = [];
  const json = () => JSON.stringify(state);
  return {
    calls,
    engineVersion: () => "fake",
    previewOpen: () => JSON.stringify({ handle: "s1" }),
    previewClose: () => "{}",
    previewState: json,
    previewSet: (_h, path, valueJson) => {
      calls.push(`set ${path} ${valueJson}`);
      const value: unknown = JSON.parse(valueJson);
      state = stateWith({
        values: { ...state.values, [path]: value as never },
        relevant: {
          ...state.relevant,
          page_q: !(path === "consent" && value === "no"),
        },
      });
      return json();
    },
    previewNext: json,
    previewPrevious: json,
    previewEnter: json,
    previewLeave: json,
    previewAddRow: (_h, repeatId) =>
      repeatId === "visits"
        ? JSON.stringify({ error: "repeat visits is at its maximum of 0" })
        : json(),
    previewDeleteRow: json,
    previewGoToFirstBlocking: json,
    previewTrace: () => "{}",
  };
}

const hides: TestCase = {
  id: "tc1",
  name: "consent hides the page",
  steps: [{ kind: "set", path: "consent", value: "no" }],
  expectations: [{ path: "page_q", relevant: false }],
};

describe("running a case", () => {
  it("passes when the engine's state says what the author expected", () => {
    const engine = fakeEngine();
    expect(runCase(engine, {}, "2026-09-07", hides)).toEqual({
      outcome: "pass",
    });
    expect(engine.calls).toEqual(['set consent "no"']);
  });

  it("fails naming the path and what was, when relevance differs", () => {
    const engine = fakeEngine();
    const stillShown: TestCase = {
      ...hides,
      steps: [{ kind: "set", path: "consent", value: "yes" }],
    };
    expect(runCase(engine, {}, "2026-09-07", stillShown)).toEqual({
      outcome: "fail",
      reason: "`page_q` expected hidden, was relevant",
    });
  });

  it("fails with the engine's own message when a step is refused", () => {
    const engine = fakeEngine();
    const refused: TestCase = {
      id: "tc2",
      name: "a visit",
      steps: [{ kind: "addRow", repeatId: "visits" }],
      expectations: [],
    };
    expect(runCase(engine, {}, "2026-09-07", refused)).toEqual({
      outcome: "fail",
      reason: "step add a row to visits: repeat visits is at its maximum of 0",
    });
  });

  it("compares values only when asked to, and tells a missing path from a wrong one", () => {
    const state = stateWith({});
    expect(
      check({ path: "total", value: 7, checkValue: true }, state),
    ).toBeNull();
    expect(check({ path: "total", value: 12, checkValue: true }, state)).toBe(
      "`total` expected 12, was 7",
    );
    expect(check({ path: "total", value: 12 }, state)).toBeNull();
    expect(check({ path: "gone", relevant: true }, state)).toBe(
      "`gone` is not in the form",
    );
  });
});
