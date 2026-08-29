/** The two guarantees the submission page makes about a private key.
 *
 * 1. It never reaches localStorage, sessionStorage, IndexedDB or any request.
 * 2. The plaintext it opens does not survive a remount.
 *
 * Both were true only because nobody had written the code that breaks them.
 * The console says "never uploaded, never stored and never logged" on screen,
 * in bold, and until this file existed that sentence was an intention.
 *
 * The ciphertext comes from `conformance/crypto`, so a passing run also says
 * the browser reads the same envelope the Python and Kotlin engines do.
 */

import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  A_DECRYPTED_ANSWER,
  PRIVATE_KEY_FILE,
  PRIVATE_KEY_HEX,
  SUBMISSION_ID,
  projectKeys,
  rendered,
  submissionDetail,
  submissionKeys,
} from "@/test/vectors";
import { renderAt, watchForEscapes, type Escapes } from "@/test/harness";

let escapes: Escapes;

function serve(url: string): unknown {
  if (url.startsWith("/health")) return { status: "ok", environment: "test" };
  if (url.includes(`/submissions/${SUBMISSION_ID}/keys`)) return submissionKeys;
  if (url.includes(`/submissions/${SUBMISSION_ID}`)) return submissionDetail;
  if (url.includes("/keys")) {
    return { projectId: submissionDetail.projectId, securityMode: "project_e2e", keys: projectKeys };
  }
  return undefined;
}

/** Hand the page the key file, the way the person at the keyboard does. */
async function loadTheKey(): Promise<void> {
  const input = await screen.findByLabelText(/private key file/i);
  const file = new File([PRIVATE_KEY_FILE], "dcp-primary-private-key.json", {
    type: "application/json",
  });
  // jsdom's File has no working .text() in every version; the page calls it.
  Object.defineProperty(file, "text", { value: () => Promise.resolve(PRIVATE_KEY_FILE) });
  fireEvent.change(input, { target: { files: [file] } });

  // Not "the click worked" — the actual plaintext, on screen. It appears in
  // both the folded state and the op log, hence findAll.
  await screen.findAllByText(A_DECRYPTED_ANSWER, {}, { timeout: 5000 });
}

afterEach(() => {
  cleanup();
  escapes.restore();
});

describe("a private key loaded to decrypt a submission", () => {
  it("decrypts the conformance vector's ciphertext in the browser", async () => {
    escapes = watchForEscapes(serve);
    renderAt(`/submissions/${SUBMISSION_ID}`);
    await loadTheKey();

    // Every value from the vector, not just the one we waited for. If this
    // drifts, the browser and the reference engines have stopped agreeing —
    // which is a release blocker, not a platform difference (docs/project-conventions.md rule 2).
    for (const path of ["name", "age", "weight_kg", "notes", "symptoms", "location"]) {
      expect(
        screen.getAllByText(rendered(path)).length,
        `${path} did not decrypt to ${rendered(path)}`,
      ).toBeGreaterThan(0);
    }
    // RTL text, through the same path — the console is Arabic-first by rule 8.
    expect(screen.getAllByText(rendered("members[i3].name")).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/decrypted in this browser/i).length).toBeGreaterThan(0);
  });

  it("never reaches localStorage, sessionStorage, IndexedDB or a request", async () => {
    escapes = watchForEscapes(serve);
    renderAt(`/submissions/${SUBMISSION_ID}`);
    await loadTheKey();

    // Requests were definitely made — otherwise "nothing leaked" is vacuous.
    expect(escapes.requests.length).toBeGreaterThan(0);

    const leaked = escapes.all().filter((entry) => entry.includes(PRIVATE_KEY_HEX));
    expect(leaked, "the private key left the tab").toEqual([]);
    expect(escapes.indexedDb, "the page opened an IndexedDB database").toEqual([]);

    // Also nothing under any other encoding this codebase uses for bytes: the
    // file itself, and the scalar with its separators stripped.
    for (const form of [PRIVATE_KEY_FILE, PRIVATE_KEY_HEX.toUpperCase()]) {
      expect(escapes.all().filter((entry) => entry.includes(form))).toEqual([]);
    }

    // And the page has not quietly parked it somewhere for the next visit.
    // And the page has not quietly parked it somewhere for the next visit.
    // Asserted on contents rather than emptiness: the router legitimately uses
    // sessionStorage for scroll restoration, and "no key" is the guarantee —
    // "no writes at all" is a different and wrong claim.
    for (const sink of [window.localStorage, window.sessionStorage]) {
      for (let i = 0; i < sink.length; i += 1) {
        const key = sink.key(i)!;
        expect(`${key}=${sink.getItem(key)}`).not.toContain(PRIVATE_KEY_HEX);
      }
    }
  });

  it("forgets the decrypted values when the page is remounted", async () => {
    escapes = watchForEscapes(serve);
    const first = renderAt(`/submissions/${SUBMISSION_ID}`);
    await loadTheKey();
    expect(screen.getAllByText(A_DECRYPTED_ANSWER).length).toBeGreaterThan(0);

    first.unmount();
    renderAt(`/submissions/${SUBMISSION_ID}`);

    // The ops come back — the page works — but nothing is open.
    await screen.findByText(SUBMISSION_ID);
    await waitFor(() => {
      expect(screen.getByLabelText(/private key file/i)).toBeInTheDocument();
    });
    expect(screen.queryAllByText(A_DECRYPTED_ANSWER)).toEqual([]);
    expect(screen.queryAllByText(rendered("members[i3].name"))).toEqual([]);
    expect(screen.queryAllByText(/decrypted in this browser/i)).toEqual([]);
  });

  it("forgets the decrypted values when the key is forgotten", async () => {
    escapes = watchForEscapes(serve);
    renderAt(`/submissions/${SUBMISSION_ID}`);
    await loadTheKey();

    fireEvent.click(screen.getByRole("button", { name: /forget key/i }));

    expect(screen.queryAllByText(A_DECRYPTED_ANSWER)).toEqual([]);
    expect(screen.getByLabelText(/private key file/i)).toBeInTheDocument();
  });
});
