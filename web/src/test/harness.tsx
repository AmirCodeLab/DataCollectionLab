/** Mounting the console under test, and watching every way out of it.
 *
 * `Escapes` is the point of the file. The guarantee these tests defend is
 * negative — the private key does not reach storage, does not reach a request —
 * and a negative guarantee is only as good as the list of places you looked.
 * So the recording is done by wrapping the sinks themselves rather than by
 * asserting against particular calls: anything written to localStorage,
 * sessionStorage or IndexedDB, and anything in any request's URL or body, is
 * captured whether or not the test anticipated it.
 */

import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  RouterProvider,
  createMemoryHistory,
  createRouter,
} from "@tanstack/react-router";
import { render, type RenderResult } from "@testing-library/react";
import { vi } from "vitest";

import { PERMISSIONS, type Me } from "@/api/types";
import { routeTree } from "@/app/router";

/** A stubbed answer with a status the test chose. */
class Reply {
  constructor(
    readonly status: number,
    readonly body: unknown,
  ) {}
}

export const reply = (status: number, body: unknown): Reply =>
  new Reply(status, body);

/** Everything that left the page, from every channel that could carry a key. */
export interface Escapes {
  /** Values written to localStorage / sessionStorage, as `key=value`. */
  storage: string[];
  /** Every request, as `METHOD url body`. */
  requests: string[];
  /** Databases IndexedDB was asked to open. */
  indexedDb: string[];
  /** Every string that left the page by any route, for one flat search. */
  all(): string[];
  /** Restore the real sinks. */
  restore(): void;
}

/** The harness's default session: an admin, every permission. */
export const SIGNED_IN_AS_ADMIN: Me = {
  userId: "01USRADMIN",
  username: "admin",
  displayName: "Test Admin",
  organizationId: "01ORGTEST",
  organizationSlug: "test",
  sessionKind: "console",
  deviceId: null,
  scopeKind: "organization",
  permissions: [...PERMISSIONS],
  expiresAt: "2099-01-01T00:00:00Z",
};

/** Wrap the storage, IndexedDB and fetch sinks so anything leaving is recorded.
 *
 * `handle` serves the API. It gets the request and returns the JSON body; the
 * default 404s, so a route a test forgot to stub fails loudly rather than
 * hanging. To answer with a status of its own — a 409 on a stale draft save,
 * a 422 with a list of violations — return `reply(status, body)`.
 */
export function watchForEscapes(
  handle: (url: string, init?: RequestInit) => unknown,
): Escapes {
  const storage: string[] = [];
  const requests: string[] = [];
  const indexedDb: string[] = [];

  // Wrap the instances, not `Storage.prototype`: the environment's own
  // localStorage may not be a real Storage at all, and a prototype patch would
  // then record nothing while looking exactly like a passing test.
  const sinks: Array<[Storage, Storage["setItem"]]> = [
    [window.localStorage, window.localStorage.setItem],
    [window.sessionStorage, window.sessionStorage.setItem],
  ];
  for (const [sink, real] of sinks) {
    sink.setItem = function setItem(key: string, value: string) {
      storage.push(`${key}=${value}`);
      return real.call(this, key, value);
    };
  }

  const realIndexedDb = globalThis.indexedDB;
  Object.defineProperty(globalThis, "indexedDB", {
    value: {
      open: (name: string) => {
        indexedDb.push(name);
        throw new Error("IndexedDB is not available in tests");
      },
    },
    configurable: true,
    writable: true,
  });

  const realFetch = globalThis.fetch;
  const fetchSpy = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const body = typeof init?.body === "string" ? init.body : "";
    requests.push(`${init?.method ?? "GET"} ${url} ${body}`);
    // Signed in as an admin holding every permission unless the test answers
    // `/auth/me` itself: the layout gates every screen on that query, and a
    // page test is about the page. The gate has its own tests (LoginPage,
    // Layout), where the handler answers 401 on purpose.
    const answered = handle(url, init);
    const payload =
      answered === undefined && url === "/api/v1/auth/me" ? SIGNED_IN_AS_ADMIN : answered;
    if (payload instanceof Reply) {
      return Promise.resolve(
        new Response(JSON.stringify(payload.body), {
          status: payload.status,
          headers: { "Content-Type": "application/json" },
        }),
      );
    }
    return Promise.resolve(
      new Response(JSON.stringify(payload ?? { detail: "not stubbed" }), {
        status: payload === undefined ? 404 : 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
  });
  globalThis.fetch = fetchSpy as unknown as typeof fetch;

  return {
    storage,
    requests,
    indexedDb,
    all: () => [...storage, ...requests, ...indexedDb],
    restore() {
      for (const [sink, real] of sinks) sink.setItem = real;
      window.localStorage.clear();
      window.sessionStorage.clear();
      globalThis.fetch = realFetch;
      Object.defineProperty(globalThis, "indexedDB", {
        value: realIndexedDb,
        configurable: true,
        writable: true,
      });
    },
  };
}

/** Mount the app at one route, over a memory history. */
export function renderAt(path: string): RenderResult {
  const queryClient = new QueryClient({
    // No retries and no cached carry-over between tests: a retry would turn a
    // deliberate 404 into a slow test, and a shared cache would let one test's
    // decrypted answers show up in the next one's assertions.
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const router = createRouter({
    routeTree,
    history: createMemoryHistory({ initialEntries: [path] }),
  });

  return render(
    (
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>
    ) as ReactElement,
  );
}
