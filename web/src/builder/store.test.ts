/** The two invariants the store holds: a compile answer for a document the
 *  author no longer has is stale, not current; and a save acknowledges only
 *  the document that was sent.
 */

import { beforeEach, describe, expect, it } from "vitest";

import type { CompileResponse } from "@/api/types";
import { emptyForm, newQuestion } from "./ir";
import { useBuilder } from "./store";

const answer: CompileResponse = {
  formId: "f",
  version: 1,
  fieldCount: 0,
  evaluationOrder: [],
  warnings: [],
  screens: [],
  instancePlans: {},
};

describe("the compile answer is never recomputed, only marked stale", () => {
  beforeEach(() => {
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 3);
  });

  it("an edit after an answer makes it stale and keeps it readable", () => {
    const s = useBuilder.getState();
    s.compileStarted(s.ir!);
    s.compileSucceeded(s.ir!, answer);
    expect(useBuilder.getState().compile.status).toBe("current");

    s.insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    const after = useBuilder.getState().compile;
    expect(after.status).toBe("stale");
    expect(after.result).toBe(answer);
  });

  it("an answer for a document that has since changed stays stale", () => {
    const s = useBuilder.getState();
    const askedFor = s.ir!;
    s.compileStarted(askedFor);
    s.insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    s.compileSucceeded(askedFor, answer);
    expect(useBuilder.getState().compile.status).toBe("stale");
    // And a refusal for an old document is not a refusal of this one.
    s.compileRefused(askedFor, ["old news"]);
    expect(useBuilder.getState().compile.status).toBe("stale");
  });

  it("a refusal for the current document is a refusal, with its reasons verbatim", () => {
    const s = useBuilder.getState();
    s.compileRefused(s.ir!, ["§10.2: a thing", "another"]);
    expect(useBuilder.getState().compile).toMatchObject({
      status: "refused",
      refusals: ["§10.2: a thing", "another"],
    });
  });
});

describe("saving", () => {
  beforeEach(() => {
    useBuilder.getState().close();
  });

  it("a new draft starts dirty; an opened one starts clean", () => {
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), null);
    expect(useBuilder.getState().save.status).toBe("dirty");
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    expect(useBuilder.getState().save.status).toBe("clean");
  });

  it("an edit during a save leaves the document dirty when the save lands", () => {
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    const s = useBuilder.getState();
    s.insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    const sent = useBuilder.getState().ir!;
    s.saveStarted();
    s.insert({ parentId: null, index: 1 }, newQuestion("b", "text", "en"));
    s.saveSucceeded(sent, 2);
    const after = useBuilder.getState();
    expect(after.revision).toBe(2);
    expect(after.saved).toBe(sent);
    expect(after.save.status).toBe("dirty");
    expect(after.ir).not.toBe(sent);
  });

  it("a conflict sticks until the page reloads the draft", () => {
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    const s = useBuilder.getState();
    s.saveConflicted("draft has moved on; current revision is 2");
    s.insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    expect(useBuilder.getState().save.status).toBe("conflict");
  });

  it("removing the selected node clears the selection", () => {
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    const s = useBuilder.getState();
    s.insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    expect(useBuilder.getState().selectedId).toBe("a");
    s.remove("a");
    expect(useBuilder.getState().selectedId).toBeNull();
  });
});

describe("test cases live with the draft", () => {
  beforeEach(() => {
    useBuilder.getState().close();
    useBuilder
      .getState()
      .open("01FORM", emptyForm("f", "F"), 1, [
        { id: "tc1", name: "one", steps: [], expectations: [] },
      ]);
  });

  it("are loaded with the draft, and an edit dirties the draft without touching the compile answer", () => {
    const s = useBuilder.getState();
    expect(s.testCases.map((c) => c.id)).toEqual(["tc1"]);
    expect(s.save.status).toBe("clean");
    s.compileStarted(s.ir!);
    s.compileSucceeded(s.ir!, answer);
    s.renameTestCase("tc1", "renamed");
    const after = useBuilder.getState();
    expect(after.testCases[0]?.name).toBe("renamed");
    expect(after.save.status).toBe("dirty");
    expect(after.compile.status).toBe("current");
    expect(after.ir).toBe(s.ir);
    s.addTestCase({ id: "tc2", name: "two", steps: [], expectations: [] });
    s.removeTestCase("tc1");
    expect(useBuilder.getState().testCases.map((c) => c.id)).toEqual(["tc2"]);
  });
});
