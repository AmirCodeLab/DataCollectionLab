/** The tree renders the document and the server's plan, and derives nothing.
 *
 * The badge assertions are the important ones. A badge that read "screen 3"
 * because the tree counted three screens above it would be a third
 * implementation of §11.1, unreachable by any vector; these tests hand the
 * tree a plan whose numbering could not be produced by counting the document
 * and assert the tree shows the plan's numbers.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CompileResponse } from "@/api/types";
import { newRepeat, type FormIr, type QuestionNode } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { badgeFor } from "./badges";
import { planDrop } from "./drop";
import { insertionSlot } from "./slots";
import { TreePane } from "./TreePane";

vi.mock("@/api/queries", () => ({
  paletteQuery: () => ({
    queryKey: ["palette"],
    queryFn: () =>
      Promise.resolve({
        version: "0.1",
        types: [
          { dataType: "text", status: "collectable", note: null },
          { dataType: "integer", status: "collectable", note: null },
          {
            dataType: "time",
            status: "in_spec_only",
            note: "REGISTRY NOTE: no client renders a time picker yet",
          },
        ],
        choiceSources: [
          { dataType: "inline", status: "collectable", note: null },
        ],
      }),
  }),
}));

vi.mock("@/builder/expressions/ExpressionEditor", () => ({
  ExpressionEditor: () => null,
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
    formId: "hh",
    version: 1,
    title: { en: "Household" },
    defaultLanguage: "en",
    languages: ["en"],
    children: [
      q("consent"),
      q("total", { calculate: { op: "lit", value: 1 } }),
      {
        type: "group",
        id: "page",
        appearance: "field-list",
        children: [q("a"), q("b")],
      },
      {
        type: "repeat",
        id: "members",
        label: { en: "Members" },
        minInstances: 0,
        children: [q("name"), q("income")],
      },
      { type: "mystery", id: "odd" },
    ],
  };
}

/** Numbering no count of the document would produce: the first question on
 *  screen 7, the field-list on screen 2. */
const plan: CompileResponse = {
  formId: "hh",
  version: 1,
  fieldCount: 6,
  evaluationOrder: [],
  warnings: [],
  screens: [
    { index: 7, kind: "questions", questionIds: ["consent"] },
    { index: 2, kind: "questions", questionIds: ["a", "b"], groupId: "page" },
    { index: 3, kind: "repeat", questionIds: [], repeatId: "members" },
  ],
  instancePlans: {
    members: [
      { index: 0, kind: "questions", questionIds: ["name"] },
      { index: 1, kind: "questions", questionIds: ["income"] },
    ],
  },
};

function mount(): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    (
      <QueryClientProvider client={client}>
        <TreePane />
      </QueryClientProvider>
    ) as ReactElement,
  );
}

beforeEach(() => {
  useBuilder.getState().close();
  useBuilder.getState().open("01FORM", form(), 1);
});
afterEach(cleanup);

describe("badges come from the plan", () => {
  it("shows the plan's numbers, the field-list's company, and the row screens", () => {
    const s = useBuilder.getState();
    s.compileStarted(s.ir!);
    s.compileSucceeded(s.ir!, plan);
    mount();
    expect(screen.getByText("screen 7")).toBeInTheDocument();
    expect(screen.getAllByText("screen 2, with 1 others")).toHaveLength(2);
    expect(screen.getByText("row screen 1")).toBeInTheDocument();
    expect(
      screen.getByText("roster — 1 screen, any number of rows"),
    ).toBeInTheDocument();
    expect(screen.getByText("computed — never asked")).toBeInTheDocument();
  });

  it("dims them and says so once the document has changed, and never renumbers", () => {
    const s = useBuilder.getState();
    s.compileStarted(s.ir!);
    s.compileSucceeded(s.ir!, plan);
    s.remove("consent");
    mount();
    // "consent" is gone and nothing below it moved up a number.
    expect(screen.queryByText("screen 7")).not.toBeInTheDocument();
    const badge = screen.getAllByText("screen 2, with 1 others")[0]!;
    expect(badge.closest("span")).toHaveClass("opacity-50");
    expect(screen.getAllByText("(stale)").length).toBeGreaterThan(0);
  });

  it("shows nothing before a compile, and nothing for a question the plan omits", () => {
    mount();
    expect(screen.queryByText(/screen/)).not.toBeInTheDocument();
    expect(
      screen.queryByText("computed — never asked"),
    ).not.toBeInTheDocument();
    const orphan = { ...q("nowhere") };
    const path = {
      node: orphan,
      parent: null,
      index: 0,
      ancestors: [],
      repeat: null,
    };
    expect(badgeFor(path, plan)).toBeNull();
  });

  it("names a node type it does not know without touching it", () => {
    mount();
    expect(screen.getAllByText("unrecognised node").length).toBeGreaterThan(0);
    expect(useBuilder.getState().ir!.children[4]).toEqual({
      type: "mystery",
      id: "odd",
    });
  });
});

describe("adding from the palette", () => {
  it("shows an in_spec_only type disabled with the registry's note verbatim", async () => {
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Add…" }));
    const time = await screen.findByRole("menuitem", { name: /time/ });
    expect(time).toBeDisabled();
    expect(time).toHaveTextContent(
      "REGISTRY NOTE: no client renders a time picker yet",
    );
    expect(screen.getByRole("menuitem", { name: /integer/ })).toBeEnabled();
  });

  it("inserts after the selection with a unique id, and at the end of a selected container", async () => {
    useBuilder.getState().select("consent");
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Add…" }));
    fireEvent.click(await screen.findByRole("menuitem", { name: /^text$/ }));
    const ir = useBuilder.getState().ir!;
    expect(ir.children.map((n) => n.id).slice(0, 2)).toEqual([
      "consent",
      "text",
    ]);
    expect(useBuilder.getState().selectedId).toBe("text");

    expect(insertionSlot(ir, "members")).toEqual({
      parentId: "members",
      index: 2,
    });
    expect(insertionSlot(ir, null)).toEqual({
      parentId: null,
      index: ir.children.length,
    });
  });
});

describe("moving", () => {
  it("refuses a repeat into a repeat with the reason, before anything moves", () => {
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newRepeat("outer", "en"));
    const ir = useBuilder.getState().ir!;
    const outcome = planDrop(ir, "outer", {
      slot: { parentId: "members", index: 0 },
      label: "into members",
    });
    expect(outcome.refusal).toMatch(/inside/);
    const asGroup = planDrop(ir, "members", {
      slot: { parentId: "page", index: 0 },
      label: "into page",
    });
    expect(asGroup.refusal).toMatch(/field-list/);
    expect(
      planDrop(ir, "a", { slot: { parentId: null, index: 0 }, label: "" })
        .refusal,
    ).toBeNull();
  });

  it("the keyboard fallback moves the selected row", () => {
    useBuilder.getState().select("total");
    mount();
    fireEvent.click(screen.getByRole("button", { name: "move up" }));
    expect(
      useBuilder
        .getState()
        .ir!.children.map((n) => n.id)
        .slice(0, 2),
    ).toEqual(["total", "consent"]);
  });

  it("deletes in two steps and names the children going with it", () => {
    useBuilder.getState().select("page");
    mount();
    fireEvent.click(screen.getByRole("button", { name: "delete page" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent(
      "and its 2 children",
    );
    expect(
      useBuilder.getState().ir!.children.some((n) => n.id === "page"),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "delete" }));
    expect(
      useBuilder.getState().ir!.children.some((n) => n.id === "page"),
    ).toBe(false);
    expect(useBuilder.getState().selectedId).toBeNull();
  });
});
