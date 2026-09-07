/** The pane runs the cases when the server has answered for the document,
 *  and shows the engine's verdict — or that there is no engine. */

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { TestCase } from "@/api/types";
import {
  useEngineModule,
  type EngineModule,
  type PreviewState,
} from "@/builder/engine/facade";
import { emptyForm } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { TestModePane } from "./TestModePane";

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
  values: { a: "x" },
  relevant: { a: true },
  valid: { a: true },
};

const engine: EngineModule = {
  engineVersion: () => "fake",
  previewOpen: () => JSON.stringify({ handle: "s1" }),
  previewClose: () => "{}",
  previewState: () => JSON.stringify(state),
  previewSet: () => JSON.stringify(state),
  previewNext: () => JSON.stringify(state),
  previewPrevious: () => JSON.stringify(state),
  previewEnter: () => JSON.stringify(state),
  previewLeave: () => JSON.stringify(state),
  previewAddRow: () => JSON.stringify(state),
  previewDeleteRow: () => JSON.stringify(state),
  previewGoToFirstBlocking: () => JSON.stringify(state),
  previewTrace: () => "{}",
};

const passing: TestCase = {
  id: "p",
  name: "a is shown",
  steps: [{ kind: "set", path: "a", value: "x" }],
  expectations: [{ path: "a", relevant: true }],
};
const failing: TestCase = {
  id: "f",
  name: "a is hidden",
  steps: [],
  expectations: [{ path: "a", relevant: false }],
};

describe("TestModePane", () => {
  beforeEach(() => {
    useEngineModule(engine);
    useBuilder.getState().close();
    useBuilder
      .getState()
      .open("01FORM", emptyForm("f", "F"), 1, [passing, failing]);
  });
  afterEach(() => {
    cleanup();
    useEngineModule(null);
  });

  it("runs every case once the compile answer is current and shows the first failure", async () => {
    render(<TestModePane />);
    expect(screen.getAllByText(/not run/)).toHaveLength(2);
    const s = useBuilder.getState();
    s.compileStarted(s.ir!);
    s.compileSucceeded(s.ir!, {
      formId: "f",
      version: 1,
      fieldCount: 1,
      evaluationOrder: ["a"],
      warnings: [],
      screens: [],
      instancePlans: {},
    });
    await screen.findByText("pass");
    expect(screen.getByRole("alert")).toHaveTextContent(
      "`a` expected hidden, was relevant",
    );
  });

  it("says the engine is unavailable rather than pretending", async () => {
    useEngineModule(null);
    // A loader with no module rejects the import of the real bundle in jsdom.
    render(<TestModePane />);
    await waitFor(() =>
      expect(screen.getByRole("note")).toHaveTextContent(
        /engine is unavailable/,
      ),
    );
  });

  it("removing a case dirties the draft and drops it from the list", async () => {
    render(<TestModePane />);
    expect(useBuilder.getState().save.status).toBe("clean");
    screen.getByRole("button", { name: "remove a is hidden" }).click();
    await waitFor(() =>
      expect(screen.queryByDisplayValue("a is hidden")).not.toBeInTheDocument(),
    );
    expect(useBuilder.getState().save.status).toBe("dirty");
    expect(useBuilder.getState().testCases.map((c) => c.id)).toEqual(["p"]);
  });
});
