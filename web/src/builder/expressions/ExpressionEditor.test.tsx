/** The four round-trip rules of scope §2, asserted by identity and by
 *  request count, plus the two rendering rules: an AST beyond the visual
 *  shapes is code only, and a number is shown with every digit.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ExpressionRequest, ExpressionResponse } from "@/api/types";
import type { Expr } from "@/builder/ir";
import { BEYOND_VISUAL, ExpressionEditor } from "./ExpressionEditor";
import { fixture } from "./fixture";

const expressionText =
  vi.fn<(request: ExpressionRequest) => Promise<ExpressionResponse>>();

vi.mock("@/api/queries", () => ({
  expressionText: (request: ExpressionRequest) => expressionText(request),
}));

const ref = (path: string): Expr => ({ op: "ref", path });
const lit = (value: unknown): Expr => ({ op: "lit", value });

/** A stand-in for the server: renders a fixed text, parses a fixed AST. */
function serve(
  rendered: string,
  parsed: Expr | null,
  error?: { message: string; offset: number | null },
) {
  expressionText.mockImplementation((request) => {
    if (request.expression)
      return Promise.resolve({
        expression: request.expression,
        text: rendered,
      });
    if (parsed !== null)
      return Promise.resolve({ expression: parsed, text: request.text });
    return Promise.resolve({
      error: error?.message ?? "bad",
      offset: error?.offset ?? null,
    });
  });
}

/** What the properties pane will be: a parent that hands the emitted AST
 *  back as the next `value`. A parent that did not would leave the field
 *  showing a document the AST is no longer for. */
function Parent({
  initial,
  onChange,
  ...rest
}: Omit<Parameters<typeof ExpressionEditor>[0], "value" | "onChange"> & {
  initial: Expr | undefined;
  onChange: (next: Expr | undefined) => void;
}) {
  const [value, setValue] = useState(initial);
  return (
    <ExpressionEditor
      {...rest}
      value={value}
      onChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

beforeEach(() => {
  expressionText.mockReset();
});
afterEach(cleanup);

describe("rule 1 — load never mutates", () => {
  it("opening with an AST emits nothing and asks the server nothing", () => {
    const onChange = vi.fn();
    const value: Expr = {
      op: "and",
      args: [
        { op: "gte", args: [ref("age"), lit(18)] },
        { op: "selected", args: [ref("consent"), lit("yes")] },
      ],
    };
    render(
      <ExpressionEditor
        value={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="size"
        label="Relevant"
      />,
    );
    expect(screen.getByRole("tab", { name: "Visual" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(onChange).not.toHaveBeenCalled();
    expect(expressionText).not.toHaveBeenCalled();
  });
});

describe("rule 2 — a visual edit rebuilds only the term it touched", () => {
  it("keeps the other terms as the same objects", () => {
    const onChange = vi.fn();
    const first: Expr = { op: "gte", args: [ref("age"), lit(18)] };
    const second: Expr = { op: "selected", args: [ref("consent"), lit("yes")] };
    const third: Expr = {
      op: "not",
      args: [{ op: "call", fn: "is_null", args: [ref("size")] }],
    };
    render(
      <ExpressionEditor
        value={{ op: "and", args: [first, second, third] }}
        onChange={onChange}
        ir={fixture()}
        nodeId="size"
        label="Relevant"
      />,
    );
    fireEvent.change(screen.getAllByLabelText("comparison")[0], {
      target: { value: "lt" },
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    const next = onChange.mock.calls[0][0] as Expr;
    expect(next.op).toBe("and");
    const args = next.args as Expr[];
    expect(args[0]).toEqual({ op: "lt", args: [ref("age"), lit(18)] });
    expect(args[0]).not.toBe(first);
    expect(args[1]).toBe(second);
    expect(args[2]).toBe(third);
  });

  it("removing a term leaves one, which is emitted as the term itself", () => {
    const onChange = vi.fn();
    const first: Expr = { op: "gte", args: [ref("age"), lit(18)] };
    const second: Expr = { op: "selected", args: [ref("consent"), lit("yes")] };
    render(
      <ExpressionEditor
        value={{ op: "and", args: [first, second] }}
        onChange={onChange}
        ir={fixture()}
        nodeId="size"
        label="Relevant"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "remove term 1" }));
    expect(onChange.mock.calls[0][0]).toBe(second);
  });
});

describe("rule 4 — the visual editor emits AST and never text", () => {
  it("never calls the expressions endpoint, whatever is edited", () => {
    const onChange = vi.fn();
    render(
      <ExpressionEditor
        value={undefined}
        onChange={onChange}
        ir={fixture()}
        nodeId="size"
        label="Relevant"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "+ term" }));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0]).toEqual({
      op: "eq",
      args: [ref(""), lit("")],
    });

    // Re-render with what a parent would now hold, then edit the field.
    cleanup();
    const held = onChange.mock.calls[0][0] as Expr;
    render(
      <ExpressionEditor
        value={held}
        onChange={onChange}
        ir={fixture()}
        nodeId="size"
        label="Relevant"
      />,
    );
    fireEvent.change(screen.getByLabelText("field"), {
      target: { value: "members[].income" },
    });
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange.mock.calls[1][0]).toEqual({
      op: "eq",
      args: [ref("members[].income"), lit("")],
    });
    expect(expressionText).not.toHaveBeenCalled();
  });
});

describe("the code field", () => {
  const value: Expr = { op: "gte", args: [ref("age"), lit(18)] };

  it("renders the AST to canonical text once, and rule 3: leaving it unchanged does not re-parse", async () => {
    serve("${age} >= 18", null);
    const onChange = vi.fn();
    render(
      <ExpressionEditor
        value={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        selfPath="age"
        label="Constraint"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    const field = await screen.findByDisplayValue("${age} >= 18");
    expect(expressionText).toHaveBeenCalledTimes(1);
    expect(expressionText.mock.calls[0][0]).toEqual({ expression: value });

    fireEvent.focus(field);
    fireEvent.blur(field);
    expect(expressionText).toHaveBeenCalledTimes(1);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("parses what the author typed, in the node's scope, and emits the server's AST", async () => {
    const parsed: Expr = { op: "gt", args: [ref("age"), lit(21)] };
    serve("${age} >= 18", parsed);
    const onChange = vi.fn();
    render(
      <Parent
        initial={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        selfPath="age"
        rowScope={false}
        label="Constraint"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    const field = await screen.findByDisplayValue("${age} >= 18");
    fireEvent.change(field, { target: { value: ". > 21" } });
    fireEvent.blur(field);
    await waitFor(() => expect(onChange).toHaveBeenCalledTimes(1));
    expect(expressionText.mock.calls[1][0]).toEqual({
      text: ". > 21",
      selfPath: "age",
      rowScope: false,
    });
    expect(onChange.mock.calls[0][0]).toBe(parsed);
  });

  it("parses on a pause in typing", async () => {
    vi.useFakeTimers();
    try {
      const parsed: Expr = { op: "gt", args: [ref("age"), lit(21)] };
      serve("${age} >= 18", parsed);
      const onChange = vi.fn();
      render(
        <Parent
          initial={value}
          onChange={onChange}
          ir={fixture()}
          nodeId="age"
          label="Constraint"
        />,
      );
      fireEvent.click(screen.getByRole("tab", { name: "Code" }));
      await act(async () => {
        await vi.runOnlyPendingTimersAsync();
      });
      const field = screen.getByDisplayValue("${age} >= 18");
      fireEvent.change(field, { target: { value: "${age} > 21" } });
      expect(expressionText).toHaveBeenCalledTimes(1);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(600);
      });
      expect(expressionText).toHaveBeenCalledTimes(2);
      expect(onChange).toHaveBeenCalledWith(parsed);
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the server's message with a caret at its offset, and emits nothing", async () => {
    serve("${age} >= 18", null, {
      message: "unexpected trailing '='",
      offset: 12,
    });
    const onChange = vi.fn();
    render(
      <ExpressionEditor
        value={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        label="Constraint"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    const field = await screen.findByDisplayValue("${age} >= 18");
    fireEvent.change(field, { target: { value: "${a} = ${b} = ${c}" } });
    fireEvent.blur(field);
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("unexpected trailing '='");
    expect(screen.getByTestId("caret")).toHaveTextContent("=");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("clearing the text clears the property without asking the server", async () => {
    serve("${age} >= 18", null);
    const onChange = vi.fn();
    render(
      <Parent
        initial={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        label="Constraint"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    const field = await screen.findByDisplayValue("${age} >= 18");
    fireEvent.change(field, { target: { value: "   " } });
    fireEvent.blur(field);
    expect(onChange).toHaveBeenCalledWith(undefined);
    expect(expressionText).toHaveBeenCalledTimes(1);
  });

  it("an AST with no surface form keeps the AST and says why", async () => {
    expressionText.mockResolvedValue({
      error:
        "`in` has no surface syntax. Edit this expression as IR, or use selected().",
      offset: null,
    });
    const onChange = vi.fn();
    const value: Expr = {
      op: "in",
      args: [ref("age"), { op: "call", fn: "coalesce", args: [] }],
    };
    render(
      <ExpressionEditor
        value={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        label="Relevant"
      />,
    );
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("no surface syntax");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("the picker inserts a reference at the caret", async () => {
    serve("${age} >= 18", null);
    render(
      <ExpressionEditor
        value={value}
        onChange={vi.fn()}
        ir={fixture()}
        nodeId="age"
        label="Constraint"
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "Code" }));
    const field =
      await screen.findByDisplayValue<HTMLTextAreaElement>("${age} >= 18");
    field.setSelectionRange(field.value.length, field.value.length);
    fireEvent.click(screen.getByRole("button", { name: /insert field/i }));
    fireEvent.click(screen.getByText("members[0].income"));
    expect(field).toHaveValue("${age} >= 18${members[0].income}");
  });
});

describe("beyond the visual editor", () => {
  it("shows code only, says so, and offers no conversion", async () => {
    serve("${age} + 1 > 18", null);
    const value: Expr = {
      op: "gt",
      args: [{ op: "add", args: [ref("age"), lit(1)] }, lit(18)],
    };
    render(
      <ExpressionEditor
        value={value}
        onChange={vi.fn()}
        ir={fixture()}
        nodeId="age"
        label="Relevant"
      />,
    );
    expect(screen.getByText(BEYOND_VISUAL)).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Visual" })).toBeDisabled();
    expect(screen.getByRole("tab", { name: "Code" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await screen.findByDisplayValue("${age} + 1 > 18");
    expect(screen.queryByRole("button", { name: /convert/i })).toBeNull();
  });
});

describe("numbers (A.4)", () => {
  it("shows every digit of a number literal and reads back exactly what was typed", () => {
    const onChange = vi.fn();
    const value: Expr = { op: "eq", args: [ref("size"), lit(0.1 + 0.2)] };
    render(
      <ExpressionEditor
        value={value}
        onChange={onChange}
        ir={fixture()}
        nodeId="age"
        label="Relevant"
      />,
    );
    const input = screen.getByLabelText("value");
    expect(input).toHaveValue("0.30000000000000004");

    fireEvent.change(input, { target: { value: "1e-7" } });
    fireEvent.blur(input);
    expect(onChange.mock.calls[0][0]).toEqual({
      op: "eq",
      args: [ref("size"), lit(1e-7)],
    });

    fireEvent.change(input, { target: { value: "twelve" } });
    fireEvent.blur(input);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(input).toHaveValue("0.30000000000000004");
  });
});
