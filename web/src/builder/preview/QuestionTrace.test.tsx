/** Which path is traced is decided from where the preview is — the row it
 *  is inside, else the first row that exists, else nothing to trace. */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { PreviewHandle } from "@/builder/engine/session";
import {
  emptyForm,
  type FormIr,
  type QuestionNode,
  type RepeatNode,
} from "@/builder/ir";
import { insideState, nullTrace, questionsState, rosterState } from "./fixture";
import { PreviewContext } from "./previewContext";
import { QuestionTrace } from "./QuestionTrace";
import { questionTraceKeys, tracePath } from "./tracePath";

afterEach(cleanup);

const age: QuestionNode = {
  type: "question",
  id: "age",
  dataType: "integer",
  label: { en: "Age" },
  relevant: {
    op: "eq",
    args: [
      { op: "ref", path: "consent" },
      { op: "lit", value: "yes" },
    ],
  },
  required: true,
  readOnly: { op: "lit", value: false },
};
const members: RepeatNode = {
  type: "repeat",
  id: "members",
  label: { en: "Household members" },
  children: [age],
};
const ir: FormIr = { ...emptyForm("f", "F"), children: [members] };

function handle(state: PreviewHandle["state"]): PreviewHandle & {
  traced: string[];
} {
  const traced: string[] = [];
  return {
    status: "ready",
    engine: null,
    state,
    act: () => undefined,
    answer: () => undefined,
    addRow: () => undefined,
    deleteRow: () => undefined,
    steps: () => [],
    trace: (path) => {
      traced.push(path);
      return nullTrace;
    },
    traced,
  };
}

describe("QuestionTrace", () => {
  it("offers the expressions the question has — `true` is not one", () => {
    expect(questionTraceKeys(age)).toEqual(["relevant", "readOnly"]);
  });

  it("traces the row the preview is inside", () => {
    expect(tracePath(ir, "age", insideState)).toEqual({
      path: "members[i2].age",
    });
  });

  it("outside any row, the first row that exists; with none, says so", () => {
    const withRows = {
      ...rosterState,
      relevant: { "members[i1].age": true, "members[i2].age": true },
    };
    expect(tracePath(ir, "age", withRows)).toEqual({ path: "members[i1].age" });
    expect(tracePath(ir, "age", rosterState)).toEqual({ noRowsIn: "members" });
    expect(tracePath(ir, "consent", questionsState)).toEqual({
      path: "consent",
    });
  });

  it("mounts the trace on that path, or the note, or nothing without a session", () => {
    const inside = handle(insideState);
    render(
      <PreviewContext.Provider value={inside}>
        <QuestionTrace ir={ir} node={age} />
      </PreviewContext.Provider>,
    );
    expect(inside.traced).toEqual(["members[i2].age"]);
    cleanup();

    render(
      <PreviewContext.Provider value={handle(rosterState)}>
        <QuestionTrace ir={ir} node={age} />
      </PreviewContext.Provider>,
    );
    expect(screen.getByText(/Add a row to/).textContent).toContain("members");
    cleanup();

    const { container } = render(<QuestionTrace ir={ir} node={age} />);
    expect(container).toBeEmptyDOMElement();
  });
});
