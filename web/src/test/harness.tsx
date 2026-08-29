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

import { routeTree } from "@/app/router";

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

/** Wrap the storage, IndexedDB and fetch sinks so anything leaving is recorded.
 *
 * `handle` serves the API. It gets the request and returns the JSON body; the
 * default 404s, so a route a test forgot to stub fails loudly rather than
 * hanging.
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
    const payload = handle(url, init);
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
