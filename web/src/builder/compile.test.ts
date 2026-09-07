/** The compile loop asks the server and never answers for it.
 *
 * What is asserted: a document is compiled once when opened and again after
 * an edit; one request is in flight at a time and a change during a request
 * is compiled when it lands; the object handed to the API is the store's
 * document by identity, which is what lets the store tell a current answer
 * from a stale one; and a 422 reaches the store as the server's reasons,
 * verbatim.
 */

import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type { CompileResponse } from "@/api/types";
import { emptyForm, newQuestion } from "./ir";
import { useBuilder } from "./store";

const mocks = vi.hoisted(() => ({
  compileForm:
    vi.fn<(form: Record<string, unknown>) => Promise<CompileResponse>>(),
}));
vi.mock("@/api/queries", () => ({ compileForm: mocks.compileForm }));

import { COMPILE_DEBOUNCE_MS, refusalsFrom, useAutoCompile } from "./compile";

const answer = (formId: string): CompileResponse => ({
  formId,
  version: 1,
  fieldCount: 0,
  evaluationOrder: [],
  warnings: [],
  screens: [],
  instancePlans: {},
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useAutoCompile", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    mocks.compileForm.mockReset();
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("compiles the opened document at once, with the store's object by identity", async () => {
    const first = deferred<CompileResponse>();
    mocks.compileForm.mockReturnValueOnce(first.promise);
    renderHook(() => useAutoCompile());
    await vi.advanceTimersByTimeAsync(0);

    expect(mocks.compileForm).toHaveBeenCalledTimes(1);
    const askedFor = useBuilder.getState().ir;
    expect(mocks.compileForm.mock.calls[0]?.[0]).toBe(askedFor);
    expect(useBuilder.getState().compile.status).toBe("pending");

    first.resolve(answer("f"));
    await vi.advanceTimersByTimeAsync(0);
    expect(useBuilder.getState().compile.status).toBe("current");
  });

  it("debounces edits and keeps one request in flight, compiling again when it lands", async () => {
    const first = deferred<CompileResponse>();
    mocks.compileForm.mockReturnValueOnce(first.promise);
    renderHook(() => useAutoCompile());
    await vi.advanceTimersByTimeAsync(0);
    expect(mocks.compileForm).toHaveBeenCalledTimes(1);

    // Two edits while the first request is in flight: no second request yet.
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    useBuilder
      .getState()
      .insert({ parentId: null, index: 1 }, newQuestion("b", "text", "en"));
    await vi.advanceTimersByTimeAsync(COMPILE_DEBOUNCE_MS * 2);
    expect(mocks.compileForm).toHaveBeenCalledTimes(1);

    // The first answer describes a document the author no longer has. The
    // loop starts the next request in the same tick, so the state after the
    // tick is "pending" either way; what must never happen is the answer
    // being attributed to the current document *between* the two — a frame
    // in which the plan for the old form is shown as current, without the
    // stale note. A subscriber sees every transition.
    const seen: string[] = [];
    const unsubscribe = useBuilder.subscribe((s) => {
      seen.push(s.compile.status);
    });
    const second = deferred<CompileResponse>();
    mocks.compileForm.mockReturnValueOnce(second.promise);
    first.resolve(answer("f"));
    await vi.advanceTimersByTimeAsync(0);
    unsubscribe();
    expect(seen).not.toContain("current");
    expect(seen).toContain("stale");
    expect(useBuilder.getState().compile.status).not.toBe("current");
    // ...so the current one is compiled as soon as it lands, without waiting.
    expect(mocks.compileForm).toHaveBeenCalledTimes(2);
    expect(mocks.compileForm.mock.calls[1]?.[0]).toBe(useBuilder.getState().ir);

    second.resolve(answer("f"));
    await vi.advanceTimersByTimeAsync(0);
    expect(useBuilder.getState().compile.status).toBe("current");

    // An edit after everything has landed waits the debounce, not longer.
    mocks.compileForm.mockResolvedValueOnce(answer("f"));
    useBuilder
      .getState()
      .insert({ parentId: null, index: 2 }, newQuestion("c", "text", "en"));
    await vi.advanceTimersByTimeAsync(COMPILE_DEBOUNCE_MS - 1);
    expect(mocks.compileForm).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1);
    expect(mocks.compileForm).toHaveBeenCalledTimes(3);
  });

  it("hands a 422 to the store as the server's reasons, verbatim", async () => {
    mocks.compileForm.mockRejectedValueOnce(
      new ApiError(422, "[...]", [
        "§10.2: `age` references `nobody`",
        "second reason",
      ]),
    );
    renderHook(() => useAutoCompile());
    await vi.advanceTimersByTimeAsync(0);
    expect(useBuilder.getState().compile).toMatchObject({
      status: "refused",
      refusals: ["§10.2: `age` references `nobody`", "second reason"],
    });

    // A CompileError is one string; it is one reason, not a JSON blob.
    mocks.compileForm.mockRejectedValueOnce(
      new ApiError(422, "form has no questions", "form has no questions"),
    );
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    await vi.advanceTimersByTimeAsync(COMPILE_DEBOUNCE_MS);
    expect(useBuilder.getState().compile.refusals).toEqual([
      "form has no questions",
    ]);

    // Anything else is a failure of the request, not of the form.
    mocks.compileForm.mockRejectedValueOnce(
      new ApiError(0, "API unreachable (x)"),
    );
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("b", "text", "en"));
    await vi.advanceTimersByTimeAsync(COMPILE_DEBOUNCE_MS);
    expect(useBuilder.getState().compile).toMatchObject({
      status: "failed",
      failure: "API unreachable (x)",
    });
  });
});

describe("refusalsFrom", () => {
  it("keeps a list as a list and a string as one line", () => {
    expect(refusalsFrom(new ApiError(422, "x", ["a", "b"]))).toEqual([
      "a",
      "b",
    ]);
    expect(refusalsFrom(new ApiError(422, "only", "only"))).toEqual(["only"]);
    expect(refusalsFrom(new ApiError(422, "fallback", { odd: true }))).toEqual([
      "fallback",
    ]);
  });
});
