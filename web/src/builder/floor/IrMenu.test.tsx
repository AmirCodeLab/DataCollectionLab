/** The floor: the IR goes out as it is and comes back through compile first.
 *
 * A pasted document is compiled before it replaces the draft, so a bad one is
 * refused with the server's own reason — and since a draft may hold a form
 * that does not compile, the author may still replace. Nothing pasted is
 * modified on the way in.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { CompileResponse } from "@/api/types";
import { emptyForm, newQuestion } from "@/builder/ir";
import { useBuilder } from "@/builder/store";

const mocks = vi.hoisted(() => ({
  compileForm:
    vi.fn<(form: Record<string, unknown>) => Promise<CompileResponse>>(),
}));
vi.mock("@/api/queries", () => ({ compileForm: mocks.compileForm }));

import { IrMenu } from "./IrMenu";

const pasted = {
  irVersion: "0.1",
  formId: "pasted",
  version: 4,
  title: { en: "Pasted" },
  defaultLanguage: "en",
  languages: ["en"],
  unknownKey: { kept: true },
  children: [newQuestion("a", "text", "en")],
};

describe("IrMenu", () => {
  beforeEach(() => {
    mocks.compileForm.mockReset();
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
  });
  afterEach(cleanup);

  it("shows the current document as JSON", () => {
    render(<IrMenu />);
    fireEvent.click(screen.getByRole("button", { name: "View" }));
    expect(
      screen.getByRole("dialog", { name: "the form's IR" }),
    ).toHaveTextContent('"formId": "f"');
  });

  it("compiles a pasted document before replacing, and passes it through unchanged", async () => {
    mocks.compileForm.mockResolvedValueOnce({
      formId: "pasted",
      version: 4,
      fieldCount: 1,
      evaluationOrder: ["a"],
      warnings: [],
    });
    render(<IrMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Replace…" }));
    fireEvent.change(screen.getByLabelText("IR to replace the draft with"), {
      target: { value: JSON.stringify(pasted) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check and replace" }));

    await waitFor(() =>
      expect(useBuilder.getState().ir?.formId).toBe("pasted"),
    );
    expect(mocks.compileForm).toHaveBeenCalledTimes(1);
    expect(mocks.compileForm.mock.calls[0]?.[0]).toEqual(pasted);
    expect(useBuilder.getState().ir).toEqual(pasted);
    expect(useBuilder.getState().compile.status).not.toBe("current");
  });

  it("shows a 422 verbatim and replaces only on 'replace anyway'", async () => {
    mocks.compileForm.mockRejectedValueOnce(
      new ApiError(422, "x", [
        "§10.2: `a` references `nobody`",
        "form has no questions",
      ]),
    );
    const before = useBuilder.getState().ir;
    render(<IrMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Replace…" }));
    fireEvent.change(screen.getByLabelText("IR to replace the draft with"), {
      target: { value: JSON.stringify(pasted) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check and replace" }));

    const reasons = await screen.findByRole("list", {
      name: "refusal reasons",
    });
    expect(reasons).toHaveTextContent("§10.2: `a` references `nobody`");
    expect(reasons).toHaveTextContent("form has no questions");
    expect(useBuilder.getState().ir).toBe(before);

    fireEvent.click(screen.getByRole("button", { name: /Replace anyway/ }));
    expect(useBuilder.getState().ir).toEqual(pasted);
  });

  it("refuses non-JSON and a document the editor cannot open, without asking the server", () => {
    render(<IrMenu />);
    fireEvent.click(screen.getByRole("button", { name: "Replace…" }));
    const box = screen.getByLabelText("IR to replace the draft with");
    fireEvent.change(box, { target: { value: "{not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Check and replace" }));
    expect(screen.getByText(/Not JSON/)).toBeInTheDocument();

    fireEvent.change(box, {
      target: { value: JSON.stringify({ title: "plain", children: [] }) },
    });
    fireEvent.click(screen.getByRole("button", { name: "Check and replace" }));
    expect(
      screen.getByText(/Cannot open this in the editor/),
    ).toHaveTextContent("title");
    expect(mocks.compileForm).not.toHaveBeenCalled();
  });
});
