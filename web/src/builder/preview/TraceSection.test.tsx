/** The trace lays out the engine's annotated tree and marks the null. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  PreviewSession,
  useEngineModule as installEngine,
} from "@/builder/engine/facade";
import type { PreviewHandle } from "@/builder/engine/session";
import { fakeEngine, questionsState } from "./fixture";
import { TraceSection } from "./TraceSection";

afterEach(() => {
  cleanup();
  installEngine(null);
});

describe("TraceSection", () => {
  it("renders the tree with every node's result and the null marked", () => {
    const engine = fakeEngine(questionsState);
    const session = PreviewSession.open(engine, {}, "2026-09-07");
    const preview: PreviewHandle = {
      status: "ready",
      state: questionsState,
      act: (fn) => {
        fn(session);
      },
      answer: () => undefined,
    };
    render(
      <TraceSection
        path="age"
        keys={["relevant", "constraint"]}
        preview={preview}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Trace" }));
    expect(
      engine.calls.find((c) => c.name === "previewTrace")?.args.slice(1),
    ).toEqual(["age", "relevant"]);
    const list = screen.getByRole("list", { name: "trace of relevant" });
    const lines = list.querySelectorAll("li");
    expect(lines).toHaveLength(7);
    expect(lines[0]?.textContent).toContain("and");
    expect(lines[0]?.textContent).toContain("null");
    expect(lines[0]?.className).toContain("bg-amber-50");
    expect(lines[1]?.textContent).toContain("=");
    expect(lines[1]?.textContent).toContain("true");
    expect(lines[1]?.className).not.toContain("bg-amber-50");
    expect(lines[5]?.textContent).toContain("${age}");
    expect(lines[5]?.textContent).toContain("null");
  });

  it("offers only the keys the question has, and waits for the preview", () => {
    const preview: PreviewHandle = {
      status: "loading",
      state: null,
      act: () => undefined,
      answer: () => undefined,
    };
    render(<TraceSection path="age" keys={["constraint"]} preview={preview} />);
    expect(screen.getByText(/Open the preview/)).toBeInTheDocument();
  });
});
