/** The trace lays out the engine's annotated tree, marks the null, and asks
 *  again whenever the engine's state changes. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { TraceKey, TraceNode } from "@/builder/engine/facade";
import type { PreviewHandle } from "@/builder/engine/session";
import { nullTrace, questionsState } from "./fixture";
import { TraceSection } from "./TraceSection";

afterEach(cleanup);

/** A handle whose trace is recorded, and whose tree is the fixture's. */
function handle(
  overrides: Partial<PreviewHandle> = {},
): PreviewHandle & { traced: [string, TraceKey][] } {
  const traced: [string, TraceKey][] = [];
  return {
    status: "ready",
    state: questionsState,
    act: () => undefined,
    answer: () => undefined,
    addRow: () => undefined,
    deleteRow: () => undefined,
    steps: () => [],
    trace: (path, key) => {
      traced.push([path, key]);
      return nullTrace;
    },
    traced,
    ...overrides,
  };
}

describe("TraceSection", () => {
  it("renders the tree with every node's result and the null marked", () => {
    const preview = handle();
    render(
      <TraceSection
        path="age"
        keys={["relevant", "constraint"]}
        preview={preview}
      />,
    );
    expect(preview.traced).toEqual([["age", "relevant"]]);
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

  it("offers only the keys the question has, and follows the chosen one", () => {
    const preview = handle();
    render(
      <TraceSection
        path="age"
        keys={["constraint", "calculate"]}
        preview={preview}
      />,
    );
    const select = screen.getByRole("combobox", {
      name: "expression to trace",
    });
    expect(
      Array.from(select.querySelectorAll("option")).map((o) => o.value),
    ).toEqual(["constraint", "calculate"]);
    fireEvent.change(select, { target: { value: "calculate" } });
    expect(preview.traced).toEqual([
      ["age", "constraint"],
      ["age", "calculate"],
    ]);
    expect(
      screen.getByRole("list", { name: "trace of calculate" }),
    ).toBeInTheDocument();
  });

  it("asks the engine again when its state changes, and not otherwise", () => {
    const preview = handle();
    const { rerender } = render(
      <TraceSection path="age" keys={["relevant"]} preview={preview} />,
    );
    rerender(<TraceSection path="age" keys={["relevant"]} preview={preview} />);
    expect(preview.traced).toHaveLength(1);
    const answered: PreviewHandle = {
      ...preview,
      state: { ...questionsState, values: { age: 42 } },
    };
    rerender(
      <TraceSection path="age" keys={["relevant"]} preview={answered} />,
    );
    expect(preview.traced).toHaveLength(2);
  });

  it("shows the engine's refusal as sent, and waits while it loads", () => {
    const refusing = handle({
      trace: () => {
        throw new Error("no `relevant` expression at 'age'");
      },
    });
    render(<TraceSection path="age" keys={["relevant"]} preview={refusing} />);
    expect(screen.getByRole("alert").textContent).toBe(
      "no `relevant` expression at 'age'",
    );
    cleanup();
    render(
      <TraceSection
        path="age"
        keys={["constraint"]}
        preview={handle({ status: "loading", state: null })}
      />,
    );
    expect(screen.getByText(/The engine is loading/)).toBeInTheDocument();
  });

  it("renders nothing for a question with no expressions", () => {
    const preview = handle();
    const { container } = render(
      <TraceSection path="age" keys={[]} preview={preview} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(preview.traced).toEqual([]);
  });
});

// Keep the fixture's shape honest: the tree is what `previewTrace` returns.
const _shape: TraceNode = nullTrace;
void _shape;
