/** Starting a form: one POST with exactly the three fields, then the editor. */

import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PROJECT_ID } from "@/test/vectors";
import { renderAt, watchForEscapes, type Escapes } from "@/test/harness";

let escapes: Escapes;

afterEach(() => {
  cleanup();
  escapes.restore();
  creations = 0;
});

const created = {
  id: "01NEWFORM000000000000000",
  formId: "clinic_intake",
  projectId: PROJECT_ID,
  title: "Clinic intake",
  versions: [],
  archivedAt: null,
  hasDraft: false,
  latestVersionId: null,
};
let creations = 0;

function serve(url: string, init?: RequestInit): unknown {
  if (url.startsWith("/health")) return { status: "ok", environment: "test" };
  if (url === "/api/v1/projects") {
    return {
      projects: [
        {
          id: PROJECT_ID,
          name: "Clinic study",
          slug: "clinic-study",
          securityMode: "standard",
          activeKeyCount: 0,
          createdAt: "2026-08-01T00:00:00Z",
          archivedAt: null,
        },
      ],
    };
  }
  if (url === "/api/v1/forms" && init?.method === "POST") {
    creations += 1;
    return created;
  }
  if (url === "/api/v1/forms") {
    return {
      forms: [
        ...(creations > 0 ? [created] : []),
        {
          id: "01OLDFORM000000000000000",
          formId: "hh",
          projectId: PROJECT_ID,
          title: "Household",
          versions: [1, 2],
          archivedAt: null,
          hasDraft: true,
          latestVersionId: "01V",
        },
      ],
    };
  }
  return undefined;
}

describe("the forms list", () => {
  it("tells a form with unpublished changes from one without", async () => {
    escapes = watchForEscapes(serve);
    renderAt("/forms");
    await screen.findByText("Household");
    expect(screen.getByText("unpublished changes")).toBeTruthy();
    expect(screen.getByText("1, 2")).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open draft" })).toBeTruthy();
  });

  it("refuses a form id that is not a §1 identifier, before anything is sent", async () => {
    escapes = watchForEscapes(serve);
    renderAt("/forms");
    await screen.findByText("Household");
    fireEvent.change(screen.getByLabelText("Form id"), {
      target: { value: "Clinic Intake" },
    });
    expect(screen.getByText(/lower-case letters/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "New form" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(escapes.requests.filter((r) => r.startsWith("POST"))).toHaveLength(
      0,
    );
  });

  it("creates a form with exactly projectId, formId and title, then opens it", async () => {
    escapes = watchForEscapes(serve);
    renderAt("/forms");
    await screen.findByText("Household");
    await screen.findByRole("option", { name: "Clinic study" });
    fireEvent.change(screen.getByLabelText("Project"), {
      target: { value: PROJECT_ID },
    });
    fireEvent.change(screen.getByLabelText("Form id"), {
      target: { value: "clinic_intake" },
    });
    fireEvent.change(screen.getByLabelText("Title"), {
      target: { value: " Clinic intake " },
    });
    fireEvent.click(screen.getByRole("button", { name: "New form" }));

    await waitFor(() => {
      const post = escapes.requests.find((r) =>
        r.startsWith("POST /api/v1/forms "),
      );
      expect(post).toBeDefined();
      const body: unknown = JSON.parse(
        post!.slice("POST /api/v1/forms ".length),
      );
      expect(body).toEqual({
        projectId: PROJECT_ID,
        formId: "clinic_intake",
        title: "Clinic intake",
      });
    });
    await waitFor(() =>
      expect(
        escapes.requests.some((r) =>
          r.includes("/forms/01NEWFORM000000000000000/draft"),
        ),
      ).toBe(true),
    );
  });
});
