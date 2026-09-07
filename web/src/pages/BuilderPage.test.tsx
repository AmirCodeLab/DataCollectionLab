/** The draft's lifecycle, seen from the wire.
 *
 * What these assert is what the scope doc promises and the store cannot prove
 * on its own: that the document the page sends back is the document it was
 * given, plus the edit — unknown keys and all — against the revision it
 * loaded; that a form with nothing published starts from nothing and a form
 * with versions starts from the latest one; that a stale save stops rather
 * than merges; and that a document the editor cannot open is shown, not
 * rewritten.
 *
 * The panes are not exercised here. Edits go through the store, which is the
 * one path every pane uses.
 */

import { cleanup, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PROJECT_ID } from "@/test/vectors";
import { renderAt, reply, watchForEscapes, type Escapes } from "@/test/harness";
import { newQuestion } from "@/builder/ir";
import { useBuilder } from "@/builder/store";

let escapes: Escapes;

const FORM_ROW = "01FORMROW0000000000000000";
const VERSION_ROW = "01FORMVERSION00000000000";

const loadedIr = {
  irVersion: "0.1",
  formId: "hh",
  version: 3,
  title: { en: "Household" },
  defaultLanguage: "en",
  languages: ["en"],
  // Not something this builder knows. It must come back exactly.
  xlsformSettings: { style: "pages", nested: [1, 2, { deep: true }] },
  children: [
    {
      type: "question",
      id: "consent",
      dataType: "select_one",
      label: { en: "Consent?" },
      required: true,
      choices: {
        kind: "inline",
        items: [{ value: "y", label: { en: "Yes" } }],
      },
      futureKey: "kept",
    },
    { type: "annotation", id: "a1", body: "unknown node type" },
  ],
};

const compiled = {
  formId: "hh",
  version: 3,
  fieldCount: 1,
  evaluationOrder: ["consent"],
  warnings: [],
  screens: [{ index: 0, kind: "questions", questionIds: ["consent"] }],
  instancePlans: {},
};

interface Scenario {
  hasDraft: boolean;
  versions: number[];
  latestVersionId: string | null;
  draftIr?: unknown;
  putReply?: (body: unknown) => unknown;
}

function serve(scenario: Scenario) {
  const puts: unknown[] = [];
  const handle = (url: string, init?: RequestInit): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/forms") {
      return {
        forms: [
          {
            id: FORM_ROW,
            formId: "hh",
            projectId: PROJECT_ID,
            title: "Household",
            versions: scenario.versions,
            archivedAt: null,
            hasDraft: scenario.hasDraft,
            latestVersionId: scenario.latestVersionId,
          },
        ],
      };
    }
    if (url === `/api/v1/forms/${FORM_ROW}/draft`) {
      if (init?.method === "PUT") {
        const body: unknown = JSON.parse(String(init.body));
        puts.push(body);
        if (scenario.putReply) return scenario.putReply(body);
        const sent = body as { ir: unknown; expectedRevision?: number };
        return {
          formId: FORM_ROW,
          ir: sent.ir,
          revision: (sent.expectedRevision ?? 0) + 1,
          updatedAt: "2026-09-07T00:00:00Z",
          updatedBy: null,
        };
      }
      if (!scenario.hasDraft) return undefined; // 404: no draft
      return {
        formId: FORM_ROW,
        ir: scenario.draftIr ?? loadedIr,
        revision: 7,
        updatedAt: "2026-09-07T00:00:00Z",
        updatedBy: "someone",
      };
    }
    if (url === `/api/v1/forms/versions/${VERSION_ROW}`) {
      return {
        formVersionId: VERSION_ROW,
        formId: "hh",
        version: 2,
        title: "Household",
        irChecksum: "x",
        publishedAt: "2026-09-01T00:00:00Z",
        form: { ...loadedIr, version: 2 },
      };
    }
    if (url === "/api/v1/forms/compile") return compiled;
    if (url === "/api/v1/forms/palette")
      return { version: "0.1", types: [], choiceSources: [] };
    return undefined;
  };
  return { handle, puts };
}

async function opened() {
  await waitFor(() => expect(useBuilder.getState().formId).toBe(FORM_ROW));
}

const savedRequests = () =>
  escapes.requests.filter((r) => r.startsWith("PUT "));

afterEach(() => {
  cleanup();
  escapes.restore();
  useBuilder.getState().close();
});

describe("an existing draft", () => {
  it("sends back what it loaded, plus the edit, against the loaded revision", async () => {
    const { handle, puts } = serve({
      hasDraft: true,
      versions: [1, 2],
      latestVersionId: VERSION_ROW,
    });
    escapes = watchForEscapes(handle);
    renderAt(`/forms/${FORM_ROW}`);
    await opened();

    // Opened, untouched: the document is the server's object and nothing is sent.
    expect(useBuilder.getState().revision).toBe(7);
    expect(useBuilder.getState().save.status).toBe("clean");

    useBuilder
      .getState()
      .insert(
        { parentId: null, index: 1 },
        newQuestion("age", "integer", "en"),
      );
    await waitFor(() => expect(puts).toHaveLength(1), { timeout: 4_000 });

    const sent = puts[0] as { ir: typeof loadedIr; expectedRevision: number };
    expect(sent.expectedRevision).toBe(7);
    expect(sent.ir.xlsformSettings).toEqual(loadedIr.xlsformSettings);
    expect(sent.ir.children[0]).toEqual(loadedIr.children[0]);
    expect(sent.ir.children[2]).toEqual(loadedIr.children[1]);
    expect(sent.ir.children[1]).toMatchObject({
      id: "age",
      dataType: "integer",
    });
    await waitFor(() => expect(useBuilder.getState().revision).toBe(8));
    expect(useBuilder.getState().save.status).toBe("clean");
  });

  it("stops on a conflict rather than merging, and sends nothing more", async () => {
    const { handle, puts } = serve({
      hasDraft: true,
      versions: [],
      latestVersionId: null,
      putReply: () =>
        reply(409, { detail: "draft has moved on; current revision is 9" }),
    });
    escapes = watchForEscapes(handle);
    renderAt(`/forms/${FORM_ROW}`);
    await opened();

    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    await waitFor(() => expect(puts).toHaveLength(1), { timeout: 4_000 });
    await waitFor(() =>
      expect(useBuilder.getState().save.status).toBe("conflict"),
    );
    expect(
      screen.getByRole("status", { name: "save status" }).textContent,
    ).toContain("current revision is 9");
    expect(
      screen.getByRole("status", { name: "save status" }).textContent,
    ).toContain("not merged");

    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("b", "text", "en"));
    await new Promise((r) => setTimeout(r, 2_000));
    expect(savedRequests()).toHaveLength(1);
  });

  it("shows a document it cannot open, with the reason, and never saves it", async () => {
    const { handle, puts } = serve({
      hasDraft: true,
      versions: [],
      latestVersionId: null,
      draftIr: { a: 1 },
    });
    escapes = watchForEscapes(handle);
    renderAt(`/forms/${FORM_ROW}`);
    await screen.findByText(/cannot be opened in the editor/);
    expect(screen.getByText(/children/)).toBeTruthy();
    expect(useBuilder.getState().formId).toBeNull();
    await new Promise((r) => setTimeout(r, 300));
    expect(puts).toHaveLength(0);
  });
});

describe("starting a draft", () => {
  it("from nothing when nothing is published: the first save carries no revision", async () => {
    const { handle, puts } = serve({
      hasDraft: false,
      versions: [],
      latestVersionId: null,
    });
    escapes = watchForEscapes(handle);
    renderAt(`/forms/${FORM_ROW}`);
    await opened();

    expect(useBuilder.getState().revision).toBeNull();
    expect(useBuilder.getState().ir).toMatchObject({
      formId: "hh",
      title: { en: "Household" },
      children: [],
    });

    useBuilder
      .getState()
      .insert({ parentId: null, index: 0 }, newQuestion("a", "text", "en"));
    await waitFor(() => expect(puts).toHaveLength(1), { timeout: 4_000 });
    const sent = puts[0] as Record<string, unknown>;
    expect(sent).not.toHaveProperty("expectedRevision");
    await waitFor(() => expect(useBuilder.getState().revision).toBe(1));
  });

  it("from the latest published version when there is one", async () => {
    const { handle, puts } = serve({
      hasDraft: false,
      versions: [1, 2],
      latestVersionId: VERSION_ROW,
    });
    escapes = watchForEscapes(handle);
    renderAt(`/forms/${FORM_ROW}`);
    await opened();

    expect(
      escapes.requests.some((r) =>
        r.includes(`/forms/versions/${VERSION_ROW}`),
      ),
    ).toBe(true);
    expect(useBuilder.getState().ir?.version).toBe(2);
    expect(useBuilder.getState().ir?.xlsformSettings).toEqual(
      loadedIr.xlsformSettings,
    );

    useBuilder.getState().remove("a1");
    await waitFor(() => expect(puts).toHaveLength(1), { timeout: 4_000 });
    const sent = puts[0] as { ir: typeof loadedIr };
    expect(sent.ir.children).toEqual([loadedIr.children[0]]);
    expect(sent.ir.xlsformSettings).toEqual(loadedIr.xlsformSettings);
  });
});
