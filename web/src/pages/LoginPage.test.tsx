/** Signing in: one POST, nothing kept, and the gate in front of every screen.
 *
 * The private-key test's rule holds here (proposal §3.2): the session token
 * must appear in no storage the page can reach. The harness wraps every sink
 * and the assertion is over all of them, so a "helpful" localStorage copy of
 * the cookie's value would be the first thing to fail.
 */

import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  renderAt,
  reply,
  SIGNED_IN_AS_ADMIN,
  watchForEscapes,
  type Escapes,
} from "@/test/harness";

let escapes: Escapes;

afterEach(() => {
  cleanup();
  escapes.restore();
});

const TOKEN = "s3cr3t-session-token-that-must-not-land-anywhere";

/** Signed out until the form posts; signed in as the supervisor afterwards. */
function makeServer(refuse?: { status: number; reason: string }) {
  let signedIn = false;
  return (url: string, init?: RequestInit): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/auth/login" && init?.method === "POST") {
      if (refuse) return reply(refuse.status, { detail: { reason: refuse.reason, message: "" } });
      signedIn = true;
      // What the server actually returns: who, and what they may do. The
      // token travels in Set-Cookie, which fetch keeps from the page; a body
      // carrying it would be the leak, and the harness would record it.
      return { ...SIGNED_IN_AS_ADMIN, permissions: ["submission.view"], displayName: "Sup A" };
    }
    if (url === "/api/v1/auth/me") {
      return signedIn ? { ...SIGNED_IN_AS_ADMIN, permissions: ["submission.view"] } : reply(401, { detail: { reason: "not_signed_in", message: "" } });
    }
    if (url.startsWith("/api/v1/submissions")) return { submissions: [], total: 0 };
    return undefined;
  };
}

describe("the sign-in page", () => {
  it("posts exactly the credentials, keeps nothing, and opens the screens the permissions allow", async () => {
    escapes = watchForEscapes(makeServer());
    renderAt("/login");

    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "sup-a" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => {
      expect(screen.getByText("Sup A")).toBeInTheDocument();
    });
    const post = escapes.requests.find((r) => r.startsWith("POST /api/v1/auth/login"));
    expect(post).toBe(
      'POST /api/v1/auth/login {"username":"sup-a","password":"pw","kind":"console"}',
    );
    // Nothing the page can reach holds a token: not storage, not IndexedDB.
    expect(escapes.storage).toEqual([]);
    expect(escapes.indexedDb).toEqual([]);
    expect(escapes.all().join("\n")).not.toContain(TOKEN);

    // The nav is the permissions': a supervisor sees Submissions and Forms
    // (submission.view opens both), never Projects.
    expect(screen.getByRole("link", { name: "Submissions" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Forms" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Projects" })).not.toBeInTheDocument();
  });

  it("names the refusal a pending account gets, and stays on the form", async () => {
    escapes = watchForEscapes(makeServer({ status: 403, reason: "pending_approval" }));
    renderAt("/login");

    fireEvent.change(await screen.findByLabelText("Username"), { target: { value: "new" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("waiting for approval");
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
  });
});

describe("the gate", () => {
  it("sends a visitor with no session to the sign-in form", async () => {
    escapes = watchForEscapes(makeServer());
    renderAt("/submissions");
    expect(await screen.findByLabelText("Username")).toBeInTheDocument();
    // And asked the server, rather than deciding from anything local.
    expect(escapes.requests.some((r) => r.startsWith("GET /api/v1/auth/me"))).toBe(true);
  });
});
