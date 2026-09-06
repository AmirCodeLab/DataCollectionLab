/** The document model's two promises: an edit touches only what it touched,
 *  and a document the builder did not write survives it unchanged.
 *
 * Identity, not deep equality, is the assertion throughout. "Load never
 * mutates" (scope §2) and "the builder is an editor of a document it did not
 * necessarily write" (scope §1) are both claims about object identity: a
 * subtree the author did not edit must be the same object it was loaded as,
 * so a save of it sends the bytes it received.
 */

import { describe, expect, it } from "vitest";

import {
  allIds,
  asFormIr,
  displayLabel,
  dropRefusal,
  emptyForm,
  fields,
  find,
  insertNode,
  isContainer,
  moveNode,
  newGroup,
  newQuestion,
  newRepeat,
  removeNode,
  setNodeProperty,
  uniqueId,
  updateNode,
  type FormIr,
  type IrNode,
  type QuestionNode,
} from "./ir";

const q = (id: string, extra: Partial<QuestionNode> = {}): QuestionNode => ({
  type: "question",
  id,
  dataType: "text",
  label: { en: id },
  ...extra,
});

function household(): FormIr {
  return {
    irVersion: "0.1",
    formId: "hh",
    version: 1,
    title: { en: "Household" },
    defaultLanguage: "en",
    languages: ["en", "ar"],
    // A key this builder has never heard of: it must come back untouched.
    xlsformSettings: { style: "pages" },
    children: [
      q("consent", { required: true, futureField: "kept" }),
      {
        type: "group",
        id: "hh",
        label: { en: "Household" },
        children: [
          q("size", { dataType: "integer" }),
          {
            type: "repeat",
            id: "members",
            label: { en: "Members" },
            minInstances: 0,
            children: [
              q("name"),
              q("income", { dataType: "decimal", sensitive: true }),
            ],
          },
        ],
      },
      {
        type: "group",
        id: "page",
        appearance: "field-list",
        children: [q("a"), q("b")],
      },
      {
        type: "annotation",
        id: "note_1",
        body: "not a node type this builder knows",
      },
    ],
  };
}

describe("an edit touches only what it touched", () => {
  it("returns the same siblings and the same untouched subtrees", () => {
    const before = household();
    const after = updateNode(before, "size", (node) => ({
      ...node,
      hint: { en: "people" },
    }));

    expect(after).not.toBe(before);
    expect(after.children[0]).toBe(before.children[0]);
    expect(after.children[2]).toBe(before.children[2]);
    expect(after.children[3]).toBe(before.children[3]);
    const group = after.children[1];
    const groupBefore = before.children[1];
    expect(group).not.toBe(groupBefore);
    if (!isContainer(group) || !isContainer(groupBefore))
      throw new Error("shape");
    // The sibling repeat inside the edited group is still the loaded object.
    expect(group.children[1]).toBe(groupBefore.children[1]);
    expect(group.children[0]).toEqual({
      ...q("size", { dataType: "integer" }),
      hint: { en: "people" },
    });
  });

  it("keeps keys it does not understand, on the document and on nodes", () => {
    const before = household();
    const after = setNodeProperty(before, "consent", "required", false);
    expect(after.xlsformSettings).toBe(before.xlsformSettings);
    const consent = find(after, "consent");
    expect(consent?.node.futureField).toBe("kept");
    expect(consent?.node.required).toBe(false);
  });

  it("is a no-op, by identity, when the value is already there", () => {
    const before = household();
    expect(setNodeProperty(before, "consent", "required", true)).toBe(before);
    expect(setNodeProperty(before, "consent", "hint", undefined)).toBe(before);
    expect(updateNode(before, "nobody", (n) => ({ ...n, id: "x" }))).toBe(
      before,
    );
    expect(removeNode(before, "nobody")).toBe(before);
  });

  it("removes a property with undefined and keeps an explicit null", () => {
    const before = household();
    const withNull = setNodeProperty(before, "consent", "default", null);
    expect(find(withNull, "consent")?.node).toHaveProperty("default", null);
    const without = setNodeProperty(withNull, "consent", "default", undefined);
    expect(find(without, "consent")?.node).not.toHaveProperty("default");
    expect(find(without, "consent")?.node.futureField).toBe("kept");
  });
});

describe("structure", () => {
  it("inserts at an index, at the root and inside a container", () => {
    const before = household();
    const root = insertNode(before, { parentId: null, index: 1 }, q("new"));
    expect(root.children.map((n) => n.id)).toEqual([
      "consent",
      "new",
      "hh",
      "page",
      "note_1",
    ]);
    const inner = insertNode(
      before,
      { parentId: "members", index: 99 },
      q("age"),
    );
    const members = find(inner, "members")?.node;
    if (members === undefined || !isContainer(members))
      throw new Error("shape");
    expect(members.children.map((n) => n.id)).toEqual([
      "name",
      "income",
      "age",
    ]);
    expect(inner.children[0]).toBe(before.children[0]);
  });

  it("removes a node wherever it sits", () => {
    const after = removeNode(household(), "income");
    expect(find(after, "income")).toBeNull();
    expect(allIds(after).has("name")).toBe(true);
  });

  it("moves within a list with the index corrected for the removal", () => {
    const before = household();
    // "consent" is at 0; dropping it after "hh" looks like index 2.
    const after = moveNode(before, "consent", { parentId: null, index: 2 });
    expect(after.children.map((n) => n.id)).toEqual([
      "hh",
      "consent",
      "page",
      "note_1",
    ]);
  });

  it("moves across containers", () => {
    const after = moveNode(household(), "a", { parentId: "members", index: 0 });
    expect(find(after, "a")?.repeat?.id).toBe("members");
    expect(find(after, "page")?.node).toMatchObject({ children: [q("b")] });
  });
});

describe("where a repeat may sit (the drop refusals the tree makes)", () => {
  const ir = household();
  const withOuter = insertNode(
    ir,
    { parentId: null, index: 0 },
    newRepeat("outer", "en"),
  );

  it("refuses a repeat inside a repeat, at any depth", () => {
    expect(dropRefusal(withOuter, "outer", "members")).toMatch(
      /inside a repeat/,
    );
    // A group holding a repeat is refused too: the rule is about the subtree.
    expect(dropRefusal(withOuter, "hh", "outer")).toMatch(/inside a repeat/);
  });

  it("refuses a repeat inside a field-list group", () => {
    expect(dropRefusal(ir, "members", "page")).toMatch(/field-list/);
  });

  it("refuses a node inside itself or its descendants, and inside a question", () => {
    expect(dropRefusal(ir, "hh", "hh")).toMatch(/itself/);
    expect(dropRefusal(ir, "hh", "members")).not.toBeNull();
    expect(dropRefusal(ir, "consent", "size")).toMatch(
      /only a group or a repeat/,
    );
  });

  it("allows the ordinary moves, and moveNode throws the refusal it would show", () => {
    expect(dropRefusal(ir, "size", "members")).toBeNull();
    expect(dropRefusal(ir, "members", null)).toBeNull();
    expect(dropRefusal(ir, "a", "hh")).toBeNull();
    expect(() =>
      moveNode(ir, "members", { parentId: "page", index: 0 }),
    ).toThrow(/field-list/);
  });
});

describe("what a reference picker is given", () => {
  it("lists every question with its repeat and its sensitivity, in document order", () => {
    const refs = fields(household());
    expect(refs.map((f) => f.id)).toEqual([
      "consent",
      "size",
      "name",
      "income",
      "a",
      "b",
    ]);
    expect(refs.find((f) => f.id === "income")).toMatchObject({
      repeatId: "members",
      sensitive: true,
      containers: ["hh", "members"],
      dataType: "decimal",
    });
    expect(refs.find((f) => f.id === "size")?.repeatId).toBeNull();
  });

  it("labels fall back from the default language to any language to the id", () => {
    const ir = household();
    expect(
      displayLabel(q("x", { label: { en: "Name", ar: "الاسم" } }), ir),
    ).toBe("Name");
    expect(displayLabel(q("x", { label: { ar: "الاسم" } }), ir)).toBe("الاسم");
    expect(displayLabel(q("x", { label: undefined }), ir)).toBe("x");
  });
});

describe("identifiers", () => {
  it("makes a §2.4 id from anything typed, unique in the whole form", () => {
    const ir = household();
    expect(uniqueId(ir, "Monthly Income?")).toBe("monthly_income");
    expect(uniqueId(ir, "name")).toBe("name_2");
    expect(uniqueId(ir, "12 x")).toBe("x");
    expect(uniqueId(ir, "???")).toBe("q");
  });

  it("factories produce nodes with a label in the given language", () => {
    expect(newQuestion("age", "integer", "ar")).toEqual({
      type: "question",
      id: "age",
      dataType: "integer",
      label: { ar: "age" },
    });
    expect(newGroup("g", "en").children).toEqual([]);
    expect(emptyForm("f", "Form", "fr")).toMatchObject({
      languages: ["fr"],
      defaultLanguage: "fr",
    });
  });
});

describe("opening a document the builder did not write", () => {
  it("passes unknown keys through and fills only absent header fields", () => {
    const opened = asFormIr({ children: [], whatever: 1 });
    if (!("ir" in opened)) throw new Error(opened.reason);
    expect(opened.ir).toMatchObject({
      irVersion: "0.1",
      languages: ["en"],
      defaultLanguage: "en",
      whatever: 1,
    });
  });

  it("refuses, with the reason, rather than rewriting a header into shape", () => {
    expect(asFormIr({ a: 1 })).toEqual({
      reason: expect.stringContaining("children") as string,
    });
    expect(asFormIr({ children: [], title: "plain" })).toEqual({
      reason: expect.stringContaining("title") as string,
    });
    expect(asFormIr([])).toEqual({
      reason: expect.stringContaining("not an object") as string,
    });
    expect(asFormIr({ children: [], languages: "en" })).toEqual({
      reason: expect.stringContaining("languages") as string,
    });
  });

  it("keeps a node of a type it does not know", () => {
    const ir = household();
    const foreign: IrNode | undefined = ir.children[3];
    expect(foreign?.type).toBe("annotation");
    const after = updateNode(ir, "consent", (n) => ({
      ...n,
      hint: { en: "h" },
    }));
    expect(after.children[3]).toBe(foreign);
  });
});
