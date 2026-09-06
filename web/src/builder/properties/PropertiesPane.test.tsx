/** Property edits change one node and leave every other node the object it
 *  was; an emptied property is removed rather than left as ""; an id is
 *  refused with a reason; a repeat has one row source at a time.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  find,
  type FormIr,
  type QuestionNode,
  type RepeatNode,
} from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { PropertiesPane } from "./PropertiesPane";
import { DATASET_SOURCE_NOTE, rowSourceKind, withRowSource } from "./rowSource";

vi.mock("@/api/queries", () => ({
  paletteQuery: () => ({
    queryKey: ["palette"],
    queryFn: () =>
      Promise.resolve({
        version: "0.1",
        types: [
          { dataType: "text", status: "collectable", note: null },
          { dataType: "select_one", status: "collectable", note: null },
          {
            dataType: "time",
            status: "in_spec_only",
            note: "REGISTRY NOTE for time",
          },
        ],
        choiceSources: [
          { dataType: "inline", status: "collectable", note: null },
          {
            dataType: "dataset",
            status: "in_spec_only",
            note: "REGISTRY NOTE for dataset choices",
          },
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
    languages: ["en", "ar"],
    children: [
      q("consent", { hint: { en: "Ask first" }, keptKey: "kept" }),
      q("colour", { dataType: "select_one" }),
      {
        type: "repeat",
        id: "members",
        minInstances: 0,
        countExpr: { op: "ref", path: "hh_size" },
        children: [q("name")],
      },
      { type: "group", id: "page", children: [] },
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

beforeEach(() => {
  useBuilder.getState().close();
  useBuilder.getState().open("01FORM", form(), 1);
});
afterEach(cleanup);

describe("a question", () => {
  it("edits one node and leaves the rest by identity", () => {
    useBuilder.getState().select("consent");
    const before = useBuilder.getState().ir!;
    mount();
    fireEvent.change(screen.getByLabelText("label (ar)"), {
      target: { value: "الموافقة" },
    });
    const after = useBuilder.getState().ir!;
    expect(after).not.toBe(before);
    expect(after.children[1]).toBe(before.children[1]);
    expect(after.children[2]).toBe(before.children[2]);
    expect(after.children[3]).toBe(before.children[3]);
    expect(find(after, "consent")?.node).toMatchObject({
      label: { en: "Label consent", ar: "الموافقة" },
      keptKey: "kept",
    });
  });

  it("removes an emptied property rather than leaving an empty string", () => {
    useBuilder.getState().select("consent");
    mount();
    fireEvent.change(screen.getByLabelText("hint (en)"), {
      target: { value: "" },
    });
    const node = find(useBuilder.getState().ir!, "consent")!.node;
    expect(node).not.toHaveProperty("hint");
    fireEvent.change(screen.getByLabelText("appearance"), {
      target: { value: "x" },
    });
    fireEvent.change(screen.getByLabelText("appearance"), {
      target: { value: "" },
    });
    expect(find(useBuilder.getState().ir!, "consent")!.node).not.toHaveProperty(
      "appearance",
    );
  });

  it("refuses a malformed id and a duplicate, with the reason, and applies a good one", () => {
    useBuilder.getState().select("consent");
    mount();
    const id = screen.getByLabelText(/^id/);
    fireEvent.change(id, { target: { value: "Bad Id" } });
    fireEvent.blur(id);
    expect(screen.getByText(/not an identifier/)).toBeInTheDocument();
    expect(find(useBuilder.getState().ir!, "consent")).not.toBeNull();

    fireEvent.change(id, { target: { value: "name" } });
    fireEvent.blur(id);
    expect(screen.getByText(/already used/)).toBeInTheDocument();

    fireEvent.change(id, { target: { value: "consent_given" } });
    fireEvent.blur(id);
    expect(find(useBuilder.getState().ir!, "consent_given")).not.toBeNull();
    expect(useBuilder.getState().selectedId).toBe("consent_given");
  });

  it("offers the palette's types, disabled with the note where the registry says so", async () => {
    useBuilder.getState().select("consent");
    mount();
    const option = await screen.findByRole("option", {
      name: /time — REGISTRY NOTE for time/,
    });
    expect(option).toBeDisabled();
  });

  it("required is off / always / an expression, and off removes the key", () => {
    useBuilder.getState().select("consent");
    mount();
    const mode = screen.getByLabelText("required mode");
    fireEvent.change(mode, { target: { value: "always" } });
    expect(find(useBuilder.getState().ir!, "consent")!.node.required).toBe(
      true,
    );
    fireEvent.change(mode, { target: { value: "expression" } });
    expect(find(useBuilder.getState().ir!, "consent")!.node.required).toEqual({
      op: "lit",
      value: true,
    });
    fireEvent.change(mode, { target: { value: "off" } });
    expect(find(useBuilder.getState().ir!, "consent")!.node).not.toHaveProperty(
      "required",
    );
  });

  it("choices: a source the registry marks in_spec_only is disabled with its note", async () => {
    useBuilder.getState().select("colour");
    mount();
    const dataset = await screen.findByRole("option", {
      name: /dataset — REGISTRY NOTE for dataset choices/,
    });
    expect(dataset).toBeDisabled();
    fireEvent.change(screen.getByLabelText("source"), {
      target: { value: "inline" },
    });
    fireEvent.click(screen.getByRole("button", { name: "add choice" }));
    fireEvent.change(screen.getByLabelText("choice 1 value"), {
      target: { value: "red" },
    });
    expect(find(useBuilder.getState().ir!, "colour")!.node.choices).toEqual({
      kind: "inline",
      items: [{ value: "red", label: {} }],
    });
  });
});

describe("a repeat has one row source", () => {
  it("switching source removes the other source's keys", () => {
    useBuilder.getState().select("members");
    mount();
    expect(
      rowSourceKind(
        find(useBuilder.getState().ir!, "members")!.node as RepeatNode,
      ),
    ).toBe("count");
    fireEvent.change(screen.getByLabelText(/where the rows come from/), {
      target: { value: "inline" },
    });
    let node = find(useBuilder.getState().ir!, "members")!.node;
    expect(node).not.toHaveProperty("countExpr");
    expect(node.rowSource).toEqual({ kind: "inline", items: [] });

    fireEvent.change(screen.getByLabelText(/where the rows come from/), {
      target: { value: "enumerator" },
    });
    node = find(useBuilder.getState().ir!, "members")!.node;
    expect(node).not.toHaveProperty("rowSource");
    expect(node).not.toHaveProperty("countExpr");
    expect(node.minInstances).toBe(0);
  });

  it("the sample source is disabled and carries the engine's conditions verbatim", () => {
    useBuilder.getState().select("members");
    mount();
    const option = screen.getByRole("option", { name: /rows from the sample/ });
    expect(option).toBeDisabled();
    expect(option).toHaveTextContent(DATASET_SOURCE_NOTE);
  });

  it("withRowSource is pure and keeps everything else", () => {
    const repeat = find(form(), "members")!.node as RepeatNode;
    const inline = withRowSource(repeat, "inline");
    expect(inline).toMatchObject({
      id: "members",
      minInstances: 0,
      rowSource: { kind: "inline" },
    });
    expect(inline).not.toHaveProperty("countExpr");
    expect(withRowSource(repeat, "count")).toEqual(repeat);
    expect(withRowSource(repeat, "enumerator")).not.toHaveProperty("countExpr");
  });
});

describe("the form header", () => {
  it("edits the title and the languages through the store", () => {
    mount();
    fireEvent.change(screen.getByLabelText("title (ar)"), {
      target: { value: "مسح" },
    });
    expect(useBuilder.getState().ir!.title).toEqual({
      en: "Household",
      ar: "مسح",
    });
    fireEvent.change(screen.getByLabelText("new language code"), {
      target: { value: "fr" },
    });
    fireEvent.click(screen.getByRole("button", { name: "add language" }));
    expect(useBuilder.getState().ir!.languages).toEqual(["en", "ar", "fr"]);
    fireEvent.click(screen.getByRole("button", { name: "remove language fr" }));
    expect(useBuilder.getState().ir!.languages).toEqual(["en", "ar"]);
  });
});
