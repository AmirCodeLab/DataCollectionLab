/** The pane runs the cases when the server has answered for the document,
 *  and shows the engine's verdict — or that there is no engine. */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { TestCase } from "@/api/types";
import type { EngineModule, PreviewState } from "@/builder/engine/facade";
import type { PreviewHandle } from "@/builder/engine/session";
import { emptyForm, newQuestion } from "@/builder/ir";
import { PreviewContext } from "@/builder/preview/previewContext";
import { PreviewProvider } from "@/builder/preview/PreviewProvider";
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

/** The page's arrangement: the pane under a provider holding the engine. */
const mount = (loaded: Promise<EngineModule> = Promise.resolve(engine)) =>
  render(
    <PreviewProvider engine={loaded}>
      <TestModePane />
    </PreviewProvider>,
  );

describe("TestModePane", () => {
  beforeEach(() => {
    useBuilder.getState().close();
    useBuilder
      .getState()
      .open("01FORM", emptyForm("f", "F"), 1, [passing, failing]);
  });
  afterEach(cleanup);

  it("runs every case once the compile answer is current and shows the first failure", async () => {
    mount();
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
    // An edit makes the server's answer stale, and the verdicts with it: a
    // pass shown against a document the server has not answered for is a
    // verdict on a form that no longer exists.
    act(() => {
      useBuilder
        .getState()
        .insert({ parentId: null, index: 0 }, newQuestion("x", "text", "en"));
    });
    expect(screen.queryByText("pass")).not.toBeInTheDocument();
    expect(screen.getAllByText(/waiting for the server/)).toHaveLength(2);
  });

  it("says the engine is unavailable rather than pretending", async () => {
    mount(Promise.reject(new Error("no bundle")));
    await waitFor(() =>
      expect(screen.getByRole("note")).toHaveTextContent(
        /engine is unavailable/,
      ),
    );
  });

  it("records a case from the preview's steps and the engine's state, in order", () => {
    const preview: PreviewHandle = {
      status: "ready",
      engine,
      state: {
        ...state,
        values: { a: "x", "r[i1].b": null },
        relevant: { a: true, "r[i1].b": false },
        valid: { a: true, "r[i1].b": true },
      },
      act: () => undefined,
      answer: () => undefined,
      addRow: () => undefined,
      deleteRow: () => undefined,
      steps: () => [
        { kind: "addRow", repeatId: "r" },
        { kind: "set", path: "a", value: "x" },
        { kind: "deleteRow", repeatId: "r", instanceId: "i2" },
      ],
      trace: () => {
        throw new Error("not traced here");
      },
    };
    render(
      <PreviewContext.Provider value={preview}>
        <TestModePane />
      </PreviewContext.Provider>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "New from the preview's answers" }),
    );
    const recorded = useBuilder.getState().testCases.at(-1);
    expect(recorded?.name).toBe("Case 3");
    expect(recorded?.steps).toEqual([
      { kind: "addRow", repeatId: "r" },
      { kind: "set", path: "a", value: "x" },
      { kind: "deleteRow", repeatId: "r", instanceId: "i2" },
    ]);
    expect(recorded?.expectations).toEqual([
      { path: "a", relevant: true, valid: true, value: "x", checkValue: true },
      {
        path: "r[i1].b",
        relevant: false,
        valid: true,
        value: null,
        checkValue: true,
      },
    ]);
    expect(useBuilder.getState().save.status).toBe("dirty");
  });

  it("offers no recording without a session, and none while the engine loads", () => {
    const { unmount } = render(<TestModePane />);
    expect(
      screen.queryByRole("button", { name: "New from the preview's answers" }),
    ).not.toBeInTheDocument();
    unmount();
    const loading: PreviewHandle = {
      status: "loading",
      engine: null,
      state: null,
      act: () => undefined,
      answer: () => undefined,
      addRow: () => undefined,
      deleteRow: () => undefined,
      steps: () => [],
      trace: () => {
        throw new Error("loading");
      },
    };
    render(
      <PreviewContext.Provider value={loading}>
        <TestModePane />
      </PreviewContext.Provider>,
    );
    expect(
      screen.getByRole("button", { name: "New from the preview's answers" }),
    ).toBeDisabled();
  });

  it("removing a case dirties the draft and drops it from the list", async () => {
    mount();
    expect(useBuilder.getState().save.status).toBe("clean");
    screen.getByRole("button", { name: "remove a is hidden" }).click();
    await waitFor(() =>
      expect(screen.queryByDisplayValue("a is hidden")).not.toBeInTheDocument(),
    );
    expect(useBuilder.getState().save.status).toBe("dirty");
    expect(useBuilder.getState().testCases.map((c) => c.id)).toEqual(["p"]);
  });
});
