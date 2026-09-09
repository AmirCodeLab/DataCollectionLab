/** The people screen, and the pending state made legible.
 *
 * Two viewers of the same waiting person. A supervisor reads that their
 * person is waiting on a programme manager or an administrator and sees no
 * Approve button — the permission that shows the button is the permission
 * the database reads, so the screen offers nothing the policy would refuse.
 * An admin reads "waiting for your approval" and the button posts.
 */

import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Me, Person } from "@/api/types";
import { renderAt, SIGNED_IN_AS_ADMIN, watchForEscapes, type Escapes } from "@/test/harness";

let escapes: Escapes;

afterEach(() => {
  cleanup();
  escapes.restore();
});

const SUPERVISOR: Me = {
  ...SIGNED_IN_AS_ADMIN,
  userId: "01USRSUPA",
  username: "sup-a",
  displayName: "Sup A",
  scopeKind: "team" as const,
  permissions: ["user.create", "user.assign_role", "sample.assign", "submission.view"],
  teamIds: ["01TEAMA"],
};

const waiting: Person = {
  id: "01USRNEW",
  username: "new-enum",
  displayName: "New Enumerator",
  membershipStatus: "pending_approval",
  membershipKind: "permanent",
  createdBy: "01USRSUPA",
  createdByName: "Sup A",
  createdAt: "2026-09-09T10:00:00Z",
  approvedByName: null,
  approvedAt: null,
  deactivatedAt: null,
  lastLoginAt: null,
  grants: [
    {
      id: "g1",
      roleId: "r-enum",
      roleName: "Enumerator",
      scopeKind: "team",
      projectId: null,
      teamId: "01TEAMA",
      teamName: "Team A",
      grantedAt: "2026-09-09T10:00:00Z",
    },
  ],
  teams: [{ projectId: "01P", teamId: "01TEAMA", teamName: "Team A" }],
};

function serve(me: Me, approvals: string[]) {
  return (url: string, init?: RequestInit): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/auth/me") return me;
    if (url === "/api/v1/people") return { people: [waiting] };
    if (url === "/api/v1/roles") {
      return {
        roles: [
          { id: "r-enum", name: "Enumerator", scopeKind: "team", builtin: true, permissions: [], grantable: true },
        ],
      };
    }
    if (url === "/api/v1/projects") return { projects: [] };
    if (url.startsWith("/api/v1/teams")) return { teams: [] };
    if (url === "/api/v1/people/01USRNEW/approve" && init?.method === "POST") {
      approvals.push(url);
      return { ...waiting, membershipStatus: "active", approvedByName: "Test Admin" };
    }
    return undefined;
  };
}

describe("the pending state", () => {
  it("tells the supervisor who created the person that they are waiting on someone else", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR, []));
    renderAt("/people");
    const queue = await screen.findByRole("region", { name: "waiting for approval" });
    expect(within(queue).getByText(/Your person is waiting for approval by a programme manager/)).toBeInTheDocument();
    expect(within(queue).getByText(/cannot sign in until then/)).toBeInTheDocument();
    // No button the database would refuse.
    expect(within(queue).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    // And the add form says what will happen to anyone they add.
    expect(screen.getByText(/People you add wait for approval/)).toBeInTheDocument();
  });

  it("offers the admin an Approve button that posts, and nothing else", async () => {
    const approvals: string[] = [];
    escapes = watchForEscapes(serve(SIGNED_IN_AS_ADMIN, approvals));
    renderAt("/people");
    const queue = await screen.findByRole("region", { name: "waiting for approval" });
    expect(within(queue).getByText(/Waiting for your approval — created by Sup A/)).toBeInTheDocument();
    fireEvent.click(within(queue).getByRole("button", { name: "Approve" }));
    await waitFor(() => {
      expect(approvals).toEqual(["/api/v1/people/01USRNEW/approve"]);
    });
    expect(escapes.storage).toEqual([]);
  });
});
