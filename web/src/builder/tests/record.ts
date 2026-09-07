/** Turning what is true now into what the author expects to stay true.
 *
 * A test case (scope §4, "Test mode") is the regression half of the builder:
 * a saved set of answers replayed against the draft after every edit,
 * carrying what the author expects to be true. Recording takes the steps the
 * author made in the preview and the engine's state after them, and writes
 * down relevance, validity and value for the paths the author chose — taken
 * from what the engine says now, never composed here.
 *
 * Not a conformance vector, and never stored as one; the migration comment
 * on `form_draft.test_cases` says why.
 */

import type { Expectation, TestCase, TestStep } from "@/api/types";
import type { PreviewState } from "@/builder/engine/facade";
import type { PreviewStep } from "@/builder/engine/session";

/** The preview's recorded step, in the shape the draft stores (schemas.py
 *  `TestStep`): the same three kinds, nothing inferred. */
export function toTestStep(step: PreviewStep): TestStep {
  switch (step.kind) {
    case "set":
      return { kind: "set", path: step.path, value: step.value };
    case "addRow":
      return { kind: "addRow", repeatId: step.repeatId };
    case "deleteRow":
      return {
        kind: "deleteRow",
        repeatId: step.repeatId,
        instanceId: step.instanceId,
      };
  }
}

export function recordFromState(
  name: string,
  steps: TestStep[],
  state: PreviewState,
  paths: string[],
  id: string = newCaseId(),
): TestCase {
  const expectations: Expectation[] = paths
    .filter((path) => path in state.relevant)
    .map((path) => ({
      path,
      relevant: state.relevant[path],
      valid: state.valid[path],
      value: state.values[path],
      checkValue: true,
    }));
  return { id, name, steps, expectations };
}

export function newCaseId(): string {
  return `tc_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}
