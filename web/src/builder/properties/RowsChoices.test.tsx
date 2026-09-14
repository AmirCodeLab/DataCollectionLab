/** Authoring MICS6 HL14: a question whose choices are the rows of a repeat.
 *
 * The builder is the only route a programme manager has to this feature —
 * XLSForm has no spelling for it (§3.3), so there is no importer to fall back
 * on — which makes these four claims the whole of whether it can be authored
 * at all:
 *
 * 1. the source is offered, and picking it produces a document that compiles
 *    rather than a half-filled one (`repeat: ""` is refused by both engines);
 * 2. "not the person on this row" is offered exactly where §10.2 permits it,
 *    because a checkbox that produces a form the publish gate rejects is worse
 *    than no checkbox;
 * 3. changing which roster is listed drops a flag that is no longer legal,
 *    rather than carrying it silently into a refusal;
 * 4. a roster with no summary label is called out where the author is, since
 *    §10.3's warning otherwise arrives at publish about a list that would have
 *    read 1, 2, 3.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { find, type FormIr, type QuestionNode } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { PropertiesPane } from "./PropertiesPane";

vi.mock("@/api/queries", () => ({
  paletteQuery: () => ({
    queryKey: ["palette"],
    queryFn: () =>
      Promise.resolve({
        version: "0.1",
        types: [
          { dataType: "text", status: "collectable", note: null },
          { dataType: "select_one", status: "collectable", note: null },
        ],
        choiceSources: [
          { dataType: "inline", status: "collectable", note: null },
          { dataType: "dataset", status: "collectable", note: null },
          { dataType: "rows", status: "collectable", note: null },
        ],
      }),
  }),
}));

vi.mock("@/builder/expressions/ExpressionEditor", () => ({
  ExpressionEditor: ({ label }: { label: string }) => <span>expr:{label}</span>,
}));

const q = (id: string, extra: Partial<QuestionNode> = {}): QuestionNode => ({
  type: "question",
  id,
  dataType: "select_one",
  label: { en: `Label ${id}` },
  ...extra,
});

/** The HL module's shape: a roster, a question on the row, one outside it. */
function form(summarised = true): FormIr {
  return {
    irVersion: "0.1",
    formId: "mics6_hl",
    version: 1,
    title: { en: "Household listing" },
    defaultLanguage: "en",
    languages: ["en"],
    children: [
      {
        type: "repeat",
        id: "members",
        label: { en: "List of household members" },
        allowAdd: true,
        allowDelete: true,
        ...(summarised
          ? {
              summaryLabel: { en: "{0}" },
              summaryLabelArgs: [{ op: "ref", path: "hl2_name" }],
            }
          : {}),
        children: [
          q("hl2_name", { dataType: "text" }),
          q("hl14_mother_line"),
        ],
      },
      {
        type: "repeat",
        id: "visits",
        label: { en: "Visits" },
        summaryLabel: { en: "Visit" },
        children: [q("seen_on", { dataType: "text" })],
      },
      q("respondent"),
    ],
  };
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

/** The source list comes from the palette, so it arrives after a round trip. */
async function chooseRows(): Promise<void> {
  await screen.findByRole("option", { name: "rows" });
  fireEvent.change(screen.getByLabelText("source"), {
    target: { value: "rows" },
  });
}

const choicesOf = (id: string): Record<string, unknown> =>
  (find(useBuilder.getState().ir!, id)!.node as QuestionNode)
    .choices as unknown as Record<string, unknown>;

beforeEach(() => {
  useBuilder.getState().close();
  useBuilder.getState().open("01FORM", form(), 1);
});
afterEach(cleanup);

describe("a rows choice list", () => {
  it("defaults to the repeat the question is in, which is the case it is for", async () => {
    useBuilder.getState().select("hl14_mother_line");
    mount();
    await chooseRows();

    // Not `repeat: ""`: a half-filled list is a document both engines refuse,
    // and HL14 is asked on the member's own row.
    expect(choicesOf("hl14_mother_line")).toEqual({
      kind: "rows",
      repeat: "members",
    });
  });

  it("offers the exclusion on a question inside the roster, and stores it", async () => {
    useBuilder.getState().select("hl14_mother_line");
    mount();
    await chooseRows();

    fireEvent.click(screen.getByLabelText(/not the person on this row/i));
    expect(choicesOf("hl14_mother_line")).toMatchObject({ excludeSelf: true });

    // Off removes the key rather than writing `false`, as every other
    // property in this pane does.
    fireEvent.click(screen.getByLabelText(/not the person on this row/i));
    expect(choicesOf("hl14_mother_line")).not.toHaveProperty("excludeSelf");
  });

  it("does not offer it outside the roster, and says why", async () => {
    useBuilder.getState().select("respondent");
    mount();
    await chooseRows();

    expect(
      screen.queryByLabelText(/not the person on this row/i),
    ).not.toBeInTheDocument();
    expect(screen.getByText(/no row to exclude/i)).toBeInTheDocument();
  });

  it("drops an exclusion that the new roster makes illegal", async () => {
    useBuilder.getState().select("hl14_mother_line");
    mount();
    await chooseRows();
    fireEvent.click(screen.getByLabelText(/not the person on this row/i));
    expect(choicesOf("hl14_mother_line")).toMatchObject({ excludeSelf: true });

    fireEvent.change(screen.getByLabelText(/rows of/), {
      target: { value: "visits" },
    });

    // The question is not inside `visits`, so the flag would be §10.2's
    // refusal at publish with nothing on screen to explain it.
    expect(choicesOf("hl14_mother_line")).toEqual({
      kind: "rows",
      repeat: "visits",
    });
  });

  it("warns where the author is when the roster has no summary label", async () => {
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", form(false), 1);
    useBuilder.getState().select("hl14_mother_line");
    mount();
    await chooseRows();

    expect(screen.getByText(/position numbers/i)).toBeInTheDocument();
  });
});
