/** What the console sends when it registers a project key.
 *
 * The claim on the page is absolute — "The private key is generated here and
 * downloaded to this computer. It is never sent to the server." The backend
 * defends it too (`extra="forbid"` on ProjectKeyCreate, plus a validator that
 * refuses anything shaped like a key container), but a 422 is a defence that
 * fires after the secret has already crossed the wire and landed in a request
 * log. The only place to catch it is here, before it is sent.
 *
 * So this asserts the payload by its exact key set rather than by checking a
 * `privateKey` field is absent: a field named anything at all is caught.
 */

import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PROJECT_ID } from "@/test/vectors";
import { renderAt, watchForEscapes, type Escapes } from "@/test/harness";

let escapes: Escapes;
let restoreDownload: () => void;

const project = {
  id: PROJECT_ID,
  name: "Clinic study",
  slug: "clinic-study",
  securityMode: "project_e2e" as const,
  activeKeyCount: 0,
  createdAt: "2026-08-01T00:00:00Z",
  archivedAt: null,
};

function serve(url: string, init?: RequestInit): unknown {
  if (url.startsWith("/health")) return { status: "ok", environment: "test" };
  if (url.includes("/projects") && url.includes("/keys")) {
    if (init?.method === "POST") {
      return {
        keyId: "01J9NEWKEY0000000000000000",
        projectId: PROJECT_ID,
        publicKey: "00".repeat(32),
        role: "primary",
        label: "Programme lead",
        createdAt: "2026-08-30T10:00:00Z",
        revokedAt: null,
      };
    }
    return { projectId: PROJECT_ID, securityMode: "project_e2e", keys: [] };
  }
  if (url.includes("/projects")) return { projects: [project] };
  return undefined;
}

/** Capture the private key file instead of downloading it.
 *
 * jsdom has no createObjectURL, and the test needs the file's contents anyway:
 * the scalar inside it is the string that must not appear in any request.
 */
function captureDownload(): {
  file: () => Promise<string>;
  restore: () => void;
} {
  let blob: Blob | null = null;
  const realCreate = URL.createObjectURL;
  const realRevoke = URL.revokeObjectURL;

  URL.createObjectURL = vi.fn((handed: Blob) => {
    blob = handed;
    return "blob:test";
  }) as unknown as typeof URL.createObjectURL;
  URL.revokeObjectURL = vi.fn() as unknown as typeof URL.revokeObjectURL;

  return {
    file: async () => (blob === null ? "" : await (blob as Blob).text()),
    restore() {
      URL.createObjectURL = realCreate;
      URL.revokeObjectURL = realRevoke;
    },
  };
}

afterEach(() => {
  cleanup();
  escapes.restore();
  restoreDownload();
});

describe("registering a project key", () => {
  it("sends only publicKey, role and label", async () => {
    escapes = watchForEscapes(serve);
    const download = captureDownload();
    restoreDownload = download.restore;

    renderAt(`/projects/${PROJECT_ID}/keys`);

    fireEvent.change(await screen.findByLabelText(/who holds this key/i), {
      target: { value: "Programme lead" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /generate keypair/i }));

    const post = await waitFor(() => {
      const found = escapes.requests.find((r) => r.startsWith("POST"));
      expect(found, "no key was registered").toBeDefined();
      return found!;
    });

    const body: unknown = JSON.parse(post.slice(post.indexOf("{")));
    expect(body).toBeTypeOf("object");
    const payload = body as Record<string, unknown>;

    // The whole assertion. Not "privateKey is absent" — a fourth field under
    // any name at all fails here, which is the only version of this test that
    // survives someone adding a helpful `keypair` or `backup` field.
    expect(Object.keys(payload).sort()).toEqual(["label", "publicKey", "role"]);

    expect(payload.role).toBe("primary");
    expect(payload.label).toBe("Programme lead");
    // A raw 32-byte X25519 public key, lowercase hex — not a PEM, not a JWK.
    expect(payload.publicKey).toMatch(/^[0-9a-f]{64}$/);
  });

  it("never puts the generated private key in a request", async () => {
    escapes = watchForEscapes(serve);
    const download = captureDownload();
    restoreDownload = download.restore;

    renderAt(`/projects/${PROJECT_ID}/keys`);

    fireEvent.change(await screen.findByLabelText(/who holds this key/i), {
      target: { value: "Programme lead" },
    });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.click(screen.getByRole("button", { name: /generate keypair/i }));

    await waitFor(() => {
      expect(escapes.requests.some((r) => r.startsWith("POST"))).toBe(true);
    });
    // The file is written after registration, so wait for the one thing that
    // holds the secret before asserting the secret went nowhere else.
    await waitFor(async () => {
      expect(await download.file()).toContain("privateKey");
    });

    const file: unknown = JSON.parse(await download.file());
    const scalar = (file as { privateKey: string }).privateKey;
    expect(scalar, "the downloaded file has no private key in it").toMatch(
      /^[0-9a-f]{64}$/,
    );

    // The public half is registered; the private half is in the file and
    // nowhere else — not in a request, not in storage.
    expect(escapes.all().filter((entry) => entry.includes(scalar))).toEqual([]);
    expect(window.localStorage.length, "something was written to localStorage").toBe(0);
    expect(window.sessionStorage.length, "something was written to sessionStorage").toBe(0);
  });
});
