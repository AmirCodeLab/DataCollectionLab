/** The interpolation editor emits AST, never text, and never reads a slot.
 *
 * Both are the point of the component rather than details of it
 * (`docs/builder-audit-2026-09-13.md` §4, §7):
 *
 * - **AST, never text.** Every argument is an `ExpressionEditor`, the same
 *   component `relevant` and `constraint` use, so there is one parser and it is
 *   the server's. A second path into `labelArgs` would be a second grammar.
 * - **It never reads the slots.** `{0}` has an escape (`{{`) and the engine
 *   owns that grammar in `text.slot_indices`. A copy in the console would drift
 *   on the first corner case, so the editor shows one row per *argument* and
 *   the server warns when a slot has none — which `reachability-007` pins on
 *   both engines.
 *
 * The mock here is deliberate and is what makes the first claim testable: the
 * fake `ExpressionEditor` hands back a known AST, so the assertions are about
 * what this component does with it and not about expression editing.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { find, type Expr, type FormIr, type QuestionNode } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { PropertiesPane } from "./PropertiesPane";

vi.mock("@/api/queries", () => ({
  paletteQuery: () => ({
    queryKey: ["palette"],
    queryFn: () =>
      Promise.resolve({
        version: "0.1",
        types: [{ dataType: "text", status: "collectable", note: null }],
        choiceSources: [
          { dataType: "inline", status: "collectable", note: null },
        ],
      }),
  }),
}));

/** The AST a "visual" edit would emit. Never a string. */
const EMITTED: Expr = { op: "ref", path: "member_name" };

vi.mock("@/builder/expressions/ExpressionEditor", () => ({
  ExpressionEditor: ({
    label,
    value,
    onChange,
  }: {
    label: string;
    value: Expr | undefined;
    onChange: (next: Expr | undefined) => void;
  }) => (
    <button type="button" onClick={() => onChange(EMITTED)}>
      expr:{label}:{JSON.stringify(value)}
    </button>
  ),
}));

const q = (id: string, extra: Partial<QuestionNode> = {}): QuestionNode => ({
  type: "question",
  id,
  dataType: "text",
  label: { en: `Label ${id}` },
  ...extra,
});

function form(): FormIr {
  return {
    irVersion: "0.1",
    formId: "hl",
    version: 1,
    title: { en: "HL" },
    defaultLanguage: "en",
    languages: ["en", "ur"],
    children: [
      q("member_name"),
      q("asked", { label: { en: "Is {0} resident here?", ur: "کیا {0}" } }),
      {
        type: "repeat",
        id: "members",
        summaryLabel: { en: "{0}, aged {1}" },
        children: [q("age")],
      },
    ],
  };
}

/** `find` returns a location; the node is on `.node`. */
function found(ir: FormIr, id: string): QuestionNode {
  return find(ir, id)!.node as QuestionNode;
}

function mount(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    (
      <QueryClientProvider client={client}>
        <PropertiesPane />
      </QueryClientProvider>
    ) as ReactElement,
  );
}

beforeEach(() => {
  useBuilder.getState().close();
  useBuilder.getState().open("01FORM", form(), 1);
});
afterEach(cleanup);

describe("labelArgs", () => {
  it("writes the AST the expression editor emitted, not text", () => {
    useBuilder.getState().select("asked");
    mount();

    fireEvent.click(screen.getByLabelText("add argument to labelArgs"));
    fireEvent.click(screen.getByText(/^expr:labelArgs 0:/));

    const node = found(useBuilder.getState().ir!, "asked");
    expect(node.labelArgs).toEqual([EMITTED]);
    expect(typeof node.labelArgs![0]).toBe("object");
  });

  it("does not touch the label text when an argument is added or removed", () => {
    useBuilder.getState().select("asked");
    const before = (found(useBuilder.getState().ir!, "asked"))
      .label;
    mount();

    fireEvent.click(screen.getByLabelText("add argument to labelArgs"));
    fireEvent.click(screen.getByLabelText("remove labelArgs argument 0"));

    const node = found(useBuilder.getState().ir!, "asked");
    expect(node.label).toBe(before);
    expect(node.labelArgs).toBeUndefined();
  });

  it("removes the property rather than leaving an empty array", () => {
    useBuilder.getState().select("asked");
    mount();
    fireEvent.click(screen.getByLabelText("add argument to labelArgs"));
    expect(
      (found(useBuilder.getState().ir!, "asked")).labelArgs,
    ).toHaveLength(1);
    fireEvent.click(screen.getByLabelText("remove labelArgs argument 0"));
    expect(
      (found(useBuilder.getState().ir!, "asked")).labelArgs,
    ).toBeUndefined();
  });

  it("shows one row per argument and not one per slot", () => {
    // `asked`'s label uses {0} in two languages and has no arguments. If this
    // component read the template it would render a row; it must not, because
    // reading `{0}` here would be a second copy of the engine's grammar. The
    // server warns instead — `conformance/reachability/reachability-007`.
    useBuilder.getState().select("asked");
    mount();
    expect(screen.queryByText(/^expr:labelArgs/)).toBeNull();
    // One note per args property on a question — labelArgs and
    // constraintMessageArgs — and neither of them a row.
    expect(
      screen.getAllByText(/shown to a respondent as written/),
    ).toHaveLength(2);
  });
});

describe("summaryLabelArgs", () => {
  it("is editable on a repeat, which is where a roster row gets its name", () => {
    useBuilder.getState().select("members");
    mount();
    fireEvent.click(screen.getByLabelText("add argument to summaryLabelArgs"));
    fireEvent.click(screen.getByText(/^expr:summaryLabelArgs 0:/));
    const node = find(useBuilder.getState().ir!, "members")!.node as {
      summaryLabelArgs?: Expr[];
    };
    expect(node.summaryLabelArgs).toEqual([EMITTED]);
  });
});
