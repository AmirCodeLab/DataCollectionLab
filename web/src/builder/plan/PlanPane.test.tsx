/** The plan pane renders the server's plan and never a plan of its own.
 *
 * The assertion that matters is the stale one: after an edit the old plan is
 * still on screen with its original numbers, marked stale, and an answer
 * for the old document does not make it current. The console must not
 * renumber after a delete, not even for one badge.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import type { CompileResponse } from "@/api/types";
import { newQuestion, newRepeat, type FormIr } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { PlanPane } from "./PlanPane";

const form = (): FormIr => ({
  irVersion: "0.1",
  formId: "hh",
  version: 1,
  title: { en: "Household" },
  defaultLanguage: "en",
  languages: ["en"],
  children: [
    {
      ...newQuestion("consent", "select_one", "en"),
      label: { en: "Consent?" },
    },
    {
      ...newQuestion("size", "integer", "en"),
      label: { en: "Household size" },
    },
    {
      ...newRepeat("members", "en"),
      children: [newQuestion("name", "text", "en")],
    },
  ],
});

const plan: CompileResponse = {
  formId: "hh",
  version: 1,
  fieldCount: 3,
  evaluationOrder: ["consent", "size", "members[].name"],
  warnings: ["`size` has no `ar` translation; `en` will be shown"],
  screens: [
    { index: 0, kind: "questions", questionIds: ["consent"] },
    { index: 1, kind: "questions", questionIds: ["size"] },
    { index: 2, kind: "repeat", questionIds: [], repeatId: "members" },
  ],
  instancePlans: {
    members: [{ index: 0, kind: "questions", questionIds: ["name"] }],
  },
};

describe("PlanPane", () => {
  beforeEach(() => {
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", form(), 1);
  });
  afterEach(cleanup);

  it("renders the screens, the nested instance plan once, and the warnings verbatim", () => {
    const s = useBuilder.getState();
    s.compileSucceeded(s.ir!, plan);
    render(<PlanPane />);

    expect(screen.getByRole("status")).toHaveTextContent("Current");
    const screens = within(screen.getByRole("list", { name: "screens" }));
    expect(screens.getByText("Screen 0 · questions")).toBeInTheDocument();
    expect(screens.getByText("Screen 2 · roster members")).toBeInTheDocument();
    expect(screen.getByText("Row screen 0 · questions")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Household size/ }),
    ).toBeInTheDocument();
    const warnings = within(screen.getByRole("list", { name: "warnings" }));
    expect(
      warnings.getByText("`size` has no `ar` translation; `en` will be shown"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/3 fields · 3 in evaluation order/),
    ).toBeInTheDocument();
  });

  it("after an edit, shows the old plan dimmed with its original numbers and says so", () => {
    const s = useBuilder.getState();
    const askedFor = s.ir!;
    s.compileSucceeded(askedFor, plan);
    render(<PlanPane />);

    act(() => s.remove("consent"));
    expect(screen.getByRole("status")).toHaveTextContent(/earlier version/);
    const stalePlan = screen.getByLabelText("screen plan (stale)");
    expect(stalePlan).toHaveAttribute("data-stale", "true");
    // Screen 0 still holds `consent`, and says the id is gone — no renumbering.
    expect(
      within(stalePlan).getByText("Screen 0 · questions"),
    ).toBeInTheDocument();
    expect(
      within(stalePlan).getByText("Screen 1 · questions"),
    ).toBeInTheDocument();
    expect(
      within(stalePlan).getByText(/no longer in the form/),
    ).toBeInTheDocument();

    // An answer for the old document does not make the plan current.
    act(() => s.compileSucceeded(askedFor, plan));
    expect(screen.getByRole("status")).toHaveTextContent(/earlier version/);
    // An answer for the current document does.
    act(() =>
      s.compileSucceeded(useBuilder.getState().ir!, {
        ...plan,
        screens: plan.screens!.slice(1),
      }),
    );
    expect(screen.getByRole("status")).toHaveTextContent("Current");
    expect(screen.queryByLabelText("screen plan (stale)")).toBeNull();
  });

  it("renders refusals verbatim, one per line, including a single-string detail", () => {
    const s = useBuilder.getState();
    s.compileRefused(s.ir!, [
      "§10.2: `age` references `nobody`",
      "a second\nline",
    ]);
    render(<PlanPane />);
    const items = screen.getAllByRole("listitem");
    expect(items.map((li) => li.textContent)).toEqual([
      "§10.2: `age` references `nobody`",
      "a second\nline",
    ]);
    cleanup();
    s.compileRefused(useBuilder.getState().ir!, ["form has no questions"]);
    render(<PlanPane />);
    expect(screen.getByText("form has no questions")).toBeInTheDocument();
  });

  it("shows pending and failed", () => {
    const s = useBuilder.getState();
    s.compileStarted(s.ir!);
    const { unmount } = render(<PlanPane />);
    expect(screen.getByRole("status")).toHaveTextContent("Asking the server");
    unmount();
    s.compileFailed(s.ir!, "API unreachable (x)");
    render(<PlanPane />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Could not compile: API unreachable (x)",
    );
  });

  it("clicking a question selects it in the tree and edits nothing", () => {
    const s = useBuilder.getState();
    const before = s.ir!;
    s.compileSucceeded(before, plan);
    render(<PlanPane />);
    fireEvent.click(screen.getByRole("button", { name: /Household size/ }));
    expect(useBuilder.getState().selectedId).toBe("size");
    expect(useBuilder.getState().ir).toBe(before);
    expect(screen.queryByRole("textbox")).toBeNull();
  });
});
