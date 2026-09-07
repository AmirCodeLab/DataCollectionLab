/** The preview draws the engine's state and computes none of it.
 *
 * Every assertion here is against a hand-built `PreviewState`: what is on
 * screen is what the state says, and every action becomes one call to the
 * engine whose answer replaces the screen. Nothing is derived in between.
 */

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { EngineModule } from "@/builder/engine/facade";
import { ENGINE_UNAVAILABLE } from "@/builder/engine/session";
import { emptyForm, newQuestion } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import {
  blockedEnd,
  emptyState,
  fakeEngine,
  insideState,
  questionsState,
  rosterState,
  type FakeEngine,
} from "./fixture";
import { PreviewPane } from "./PreviewPane";
import { PreviewProvider } from "./PreviewProvider";
import { usePreviewOpen } from "./previewStore";

/** The page's arrangement: the pane comes and goes, the provider stays. */
function PaneWhenOpen() {
  const open = usePreviewOpen((s) => s.open);
  return open ? <PreviewPane /> : null;
}

const mount = (loaded: Promise<EngineModule> = Promise.resolve(engine)) =>
  render(
    <PreviewProvider engine={loaded}>
      <PreviewPane />
    </PreviewProvider>,
  );

let engine: FakeEngine;

function open(...states: Parameters<typeof fakeEngine>) {
  engine = fakeEngine(...states);
  useBuilder.getState().close();
  useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
  mount();
}

const names = () => engine.calls.map((c) => c.name);

afterEach(cleanup);

describe("PreviewPane", () => {
  it("renders the questions the engine says are relevant, and nothing else", async () => {
    open(questionsState);
    await screen.findByText("Consent");
    expect(screen.getByText("Consent given? *")).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Yes" })).toBeInTheDocument();
    expect(screen.getByLabelText("Age")).toHaveValue("41");
    expect(screen.getByText("completed years")).toBeInTheDocument();
    expect(screen.getByText("This answer is required")).toBeInTheDocument();
    expect(screen.queryByText("Never shown here")).not.toBeInTheDocument();
    expect(screen.getByText("3 / 8")).toBeInTheDocument();
  });

  it("Next is one call and the screen becomes what came back", async () => {
    open(questionsState, rosterState);
    await screen.findByText("Consent");
    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    await screen.findByText("Household members");
    expect(names().filter((n) => n === "previewNext")).toHaveLength(1);
    expect(screen.getByText("5 / 8")).toBeInTheDocument();
  });

  it("an answer is one set with the path and the JSON value", async () => {
    open(questionsState, questionsState);
    await screen.findByText("Consent");
    fireEvent.change(screen.getByLabelText("Age"), { target: { value: "42" } });
    const set = engine.calls.find((c) => c.name === "previewSet");
    expect(set?.args.slice(1)).toEqual(["age", "42"]);
    fireEvent.click(screen.getByRole("radio", { name: "Yes" }));
    const sets = engine.calls.filter((c) => c.name === "previewSet");
    expect(sets[1]?.args.slice(1)).toEqual(["consent", '"yes"']);
  });

  it("the roster shows the rows, the add label, and adds through the engine", async () => {
    open(rosterState, insideState);
    await screen.findByText("Household members");
    expect(screen.getByText("Mother")).toBeInTheDocument();
    expect(screen.getByText("Father")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "delete Mother" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Add a member" }));
    expect(
      engine.calls.find((c) => c.name === "previewAddRow")?.args.slice(1),
    ).toEqual(["members"]);
    // What came back was a row: the header reads the engine's two pairs.
    await screen.findByText("Row 2 of 2 · screen 1 of 2");
    expect(
      screen.getByRole("button", { name: "Back to the list" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("father");
  });

  it("Finalize with blockers shows the count and goes to the first blocker", async () => {
    open(blockedEnd, blockedEnd);
    await screen.findByText("Cannot finalize: 3 answer(s) need attention");
    fireEvent.click(screen.getByRole("button", { name: "Finalize" }));
    expect(names()).toContain("previewGoToFirstBlocking");
  });

  it("says the form would finalize when the engine says so", async () => {
    open({ ...emptyState, progress: [8, 8], hasPrevious: true });
    await screen.findByText("This form would finalize");
  });

  it("says plainly when the engine bundle is not there", async () => {
    // The page's loader rejects when the bundle is missing; the pane shows why.
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    mount(Promise.reject(new Error("no bundle")));
    await waitFor(() =>
      expect(screen.getByRole("alert").textContent).toContain(
        ENGINE_UNAVAILABLE,
      ),
    );
  });

  it("reopens on a document change and replays the answers in order", async () => {
    open(questionsState, questionsState, questionsState, questionsState);
    await screen.findByText("Consent");
    fireEvent.change(screen.getByLabelText("Age"), { target: { value: "42" } });
    fireEvent.click(screen.getByRole("radio", { name: "Yes" }));
    engine.calls.length = 0;

    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("x", "text", "en"));
    await waitFor(() => expect(names()).toContain("previewOpen"));
    await waitFor(() =>
      expect(
        engine.calls
          .filter((c) => c.name === "previewSet")
          .map((c) => c.args.slice(1)),
      ).toEqual([
        ["age", "42"],
        ["consent", '"yes"'],
      ]),
    );
    // The old session was closed before the new one opened.
    expect(names().indexOf("previewClose")).toBeLessThan(
      names().indexOf("previewOpen"),
    );
  });

  it("typing into one answer is recorded as one step, the last value", async () => {
    open(questionsState, questionsState, questionsState, questionsState);
    await screen.findByText("Consent");
    for (const value of ["4", "42"]) {
      fireEvent.change(screen.getByLabelText("Age"), { target: { value } });
    }
    fireEvent.click(screen.getByRole("radio", { name: "Yes" }));
    expect(names().filter((n) => n === "previewSet")).toHaveLength(3);
    engine.calls.length = 0;
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("x", "text", "en"));
    await waitFor(() => expect(names()).toContain("previewOpen"));
    await waitFor(() =>
      expect(
        engine.calls
          .filter((c) => c.name === "previewSet")
          .map((c) => c.args.slice(1)),
      ).toEqual([
        ["age", "42"],
        ["consent", '"yes"'],
      ]),
    );
  });

  it("a row added in the preview is replayed on a document change, before its answers", async () => {
    open(rosterState, insideState, insideState, insideState, insideState);
    await screen.findByText("Household members");
    fireEvent.click(screen.getByRole("button", { name: "Add a member" }));
    await screen.findByText("Row 2 of 2 · screen 1 of 2");
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "uncle" },
    });
    engine.calls.length = 0;

    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("x", "text", "en"));
    await waitFor(() => expect(names()).toContain("previewOpen"));
    await waitFor(() =>
      expect(
        engine.calls
          .filter((c) => c.name === "previewAddRow" || c.name === "previewSet")
          .map((c) => [c.name, ...c.args.slice(1)]),
      ).toEqual([
        ["previewAddRow", "members"],
        ["previewSet", "members[i2].name", '"uncle"'],
      ]),
    );
  });

  it("the answers survive closing the pane: the session is the page's", async () => {
    engine = fakeEngine(questionsState, questionsState);
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
    usePreviewOpen.getState().setOpen(true);
    render(
      <PreviewProvider engine={Promise.resolve(engine)}>
        <PaneWhenOpen />
      </PreviewProvider>,
    );
    await screen.findByText("Consent");
    fireEvent.change(screen.getByLabelText("Age"), { target: { value: "42" } });
    act(() => usePreviewOpen.getState().setOpen(false));
    expect(screen.queryByText("Consent")).not.toBeInTheDocument();
    act(() => usePreviewOpen.getState().setOpen(true));
    await screen.findByText("Consent");
    expect(names().filter((n) => n === "previewOpen")).toHaveLength(1);
    expect(names().filter((n) => n === "previewSet")).toHaveLength(1);
  });

  it("selecting a question in the preview selects it in the tree", async () => {
    open(questionsState);
    await screen.findByText("Consent");
    fireEvent.click(screen.getByRole("button", { name: "Age" }));
    expect(useBuilder.getState().selectedId).toBe("age");
  });
});
