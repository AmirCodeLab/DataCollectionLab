/** Publishing sends the document through the one route, and shows what the
 *  server said — never a rephrasing of it.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/client";
import type {
  PublishVersionRequest,
  PublishVersionResponse,
} from "@/api/types";
import { emptyForm, newQuestion } from "@/builder/ir";
import { useBuilder } from "@/builder/store";

const mocks = vi.hoisted(() => ({
  publishVersion:
    vi.fn<
      (request: PublishVersionRequest) => Promise<PublishVersionResponse>
    >(),
}));
vi.mock("@/api/queries", () => ({ publishVersion: mocks.publishVersion }));

import { PublishButton } from "./PublishButton";

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(
    <QueryClientProvider client={client}>
      <PublishButton projectId="01PROJ" />
    </QueryClientProvider>,
  );
  return { invalidate };
}

describe("PublishButton", () => {
  beforeEach(() => {
    mocks.publishVersion.mockReset();
    useBuilder.getState().close();
    useBuilder.getState().open("01FORM", emptyForm("f", "F"), 1);
  });
  afterEach(cleanup);

  it("sends exactly the project, the document, the environments and the author", async () => {
    mocks.publishVersion.mockResolvedValueOnce({
      id: "01VER",
      formId: "01FORM",
      version: 2,
      irChecksum: "abc",
      publishedAt: "2026-09-07T00:00:00Z",
      created: true,
      warnings: ["`a` has no `ar` translation"],
      deployments: ["staging"],
    });
    const { invalidate } = mount();
    fireEvent.click(screen.getByRole("button", { name: "Publish…" }));
    fireEvent.click(screen.getByLabelText("staging"));
    fireEvent.change(screen.getByLabelText(/Published by/), {
      target: { value: " amir " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));

    await screen.findByRole("status");
    expect(mocks.publishVersion).toHaveBeenCalledTimes(1);
    const sent = mocks.publishVersion.mock.calls[0]?.[0];
    expect(sent).toEqual({
      projectId: "01PROJ",
      form: useBuilder.getState().ir,
      deployTo: ["staging"],
      publishedBy: "amir",
    });
    expect(Object.keys(sent ?? {}).sort()).toEqual([
      "deployTo",
      "form",
      "projectId",
      "publishedBy",
    ]);
    expect(sent?.form).toBe(useBuilder.getState().ir);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Published as version 2",
    );
    expect(screen.getByRole("list", { name: "warnings" })).toHaveTextContent(
      "`a` has no `ar` translation",
    );
    await waitFor(() =>
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["forms"] }),
    );
  });

  it("omits publishedBy when blank, and warns when the draft is unsaved", async () => {
    mocks.publishVersion.mockResolvedValueOnce({
      id: "01VER",
      formId: "01FORM",
      version: 1,
      irChecksum: "abc",
      publishedAt: null,
      created: false,
      warnings: [],
      deployments: [],
    });
    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Publish…" }));
    expect(screen.getByRole("note")).toHaveTextContent(
      /Unsaved changes will be published/,
    );
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    await screen.findByRole("status");
    expect(mocks.publishVersion.mock.calls[0]?.[0]).toEqual({
      projectId: "01PROJ",
      form: useBuilder.getState().ir,
      deployTo: [],
    });
  });

  it("renders violations verbatim, one per line", async () => {
    mocks.publishVersion.mockRejectedValueOnce(
      new ApiError(422, "x", [
        "`income` is read by `total`, which is not sensitive",
        "form has no questions",
      ]),
    );
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Publish…" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    const list = await screen.findByRole("list", { name: "violations" });
    const items = Array.from(list.querySelectorAll("li")).map(
      (li) => li.textContent,
    );
    expect(items).toEqual([
      "`income` is read by `total`, which is not sensitive",
      "form has no questions",
    ]);
  });

  it("shows any other failure as what it was", async () => {
    mocks.publishVersion.mockRejectedValueOnce(
      new ApiError(0, "API unreachable (x)"),
    );
    mount();
    fireEvent.click(screen.getByRole("button", { name: "Publish…" }));
    fireEvent.click(screen.getByRole("button", { name: "Publish" }));
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Could not publish: API unreachable (x)",
    );
  });
});
