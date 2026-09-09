/** The roles screen offers only what the database will accept.
 *
 * The break named before the screen was written: a permission editable in
 * the UI that the policy does not read. So a permission the viewer does not
 * hold is disabled, a standard role is read-only, and the one edit that is
 * offered is the one that posts.
 */

import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Me } from "@/api/types";
import { renderAt, SIGNED_IN_AS_ADMIN, watchForEscapes, type Escapes } from "@/test/harness";

let escapes: Escapes;

afterEach(() => {
  cleanup();
  escapes.restore();
});

const SUPERVISOR: Me = {
  ...SIGNED_IN_AS_ADMIN,
  scopeKind: "team" as const,
  permissions: ["user.create", "user.assign_role", "sample.assign", "submission.view"],
  teamIds: ["01TEAMA"],
};

function serve(me: Me, puts: string[]) {
  return (url: string, init?: RequestInit): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/auth/me") return me;
    if (url === "/api/v1/roles") {
      return {
        roles: [
          {
            id: "r-sup",
            name: "Supervisor",
            scopeKind: "team",
            builtin: true,
            permissions: ["user.create", "user.assign_role", "sample.assign", "submission.view"],
            grantable: true,
          },
          {
            id: "r-viewer",
            name: "Viewer",
            scopeKind: "team",
            builtin: false,
            permissions: ["submission.view"],
            grantable: true,
          },
        ],
      };
    }
    if (url === "/api/v1/roles/r-viewer/permissions" && init?.method === "PUT") {
      puts.push(String(init.body));
      return { id: "r-viewer", name: "Viewer", scopeKind: "team", builtin: false, permissions: [], grantable: true };
    }
    return undefined;
  };
}

describe("the roles screen", () => {
  it("disables what the viewer does not hold, and the standard roles entirely", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR, []));
    renderAt("/roles");
    const viewer = await screen.findByRole("listitem", { name: "Viewer" });
    // Held: editable. Not held: disabled, whatever the database would say.
    expect(within(viewer).getByRole("checkbox", { name: "Viewer: submission.view" })).toBeEnabled();
    expect(within(viewer).getByRole("checkbox", { name: "Viewer: export.download" })).toBeDisabled();
    const supervisor = screen.getByRole("listitem", { name: "Supervisor" });
    expect(within(supervisor).getByText("standard role, not editable")).toBeInTheDocument();
    expect(within(supervisor).getByRole("checkbox", { name: "Supervisor: user.create" })).toBeDisabled();
    // The new-role form disables the same permissions.
    expect(screen.getByRole("checkbox", { name: "new role: export.download" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "new role: submission.view" })).toBeEnabled();
  });

  it("puts the edited permission set, and nothing lands in storage", async () => {
    const puts: string[] = [];
    escapes = watchForEscapes(serve(SIGNED_IN_AS_ADMIN, puts));
    renderAt("/roles");
    const viewer = await screen.findByRole("listitem", { name: "Viewer" });
    fireEvent.click(within(viewer).getByRole("checkbox", { name: "Viewer: submission.view" }));
    await waitFor(() => {
      expect(puts).toEqual(['{"permissions":[]}']);
    });
    expect(escapes.storage).toEqual([]);
  });
});
