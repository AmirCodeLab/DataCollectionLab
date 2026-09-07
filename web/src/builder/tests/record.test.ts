import { describe, expect, it } from "vitest";

import type { PreviewState } from "@/builder/engine/facade";
import { recordFromState } from "./record";

const state: PreviewState = {
  screen: null,
  inside: null,
  progress: [1, 1],
  hasNext: false,
  hasPrevious: false,
  questions: [],
  roster: null,
  canFinalize: true,
  blockers: [],
  values: { consent: "no", page_q: null },
  relevant: { consent: true, page_q: false },
  valid: { consent: true, page_q: true },
};

describe("recording a case from the engine's state", () => {
  it("writes down relevance, validity and value for the chosen paths, as they are now", () => {
    const testCase = recordFromState(
      "consent hides the page",
      [{ kind: "set", path: "consent", value: "no" }],
      state,
      ["page_q", "consent", "not_a_field"],
      "tc1",
    );
    expect(testCase).toEqual({
      id: "tc1",
      name: "consent hides the page",
      steps: [{ kind: "set", path: "consent", value: "no" }],
      expectations: [
        {
          path: "page_q",
          relevant: false,
          valid: true,
          value: null,
          checkValue: true,
        },
        {
          path: "consent",
          relevant: true,
          valid: true,
          value: "no",
          checkValue: true,
        },
      ],
    });
  });
});
