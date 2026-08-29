/** Does the leak detector detect leaks?
 *
 * The tests next door assert a negative — the key is in no storage and no
 * request. A negative passes just as cheerfully when the instrument is broken,
 * and this suite came within one line of exactly that: under this jsdom
 * `window.localStorage` reads back undefined, so an app writing a key to it
 * would have thrown, the write would never have happened, and the test would
 * have reported "nothing leaked" about a channel it could not observe.
 *
 * So the instrument is tested too. Every sink `watchForEscapes` claims to
 * watch is written to here, on purpose, and must show up in `all()`. If one of
 * these fails, the guarantees next door are unproven whatever they report.
 */

import { afterEach, describe, expect, it } from "vitest";

import { watchForEscapes, type Escapes } from "./harness";

const SECRET = "40474e555c636a71787f868d949ba2a9b0b7bec5ccd3dae1e8eff6fd040b1219";

let escapes: Escapes;

afterEach(() => escapes.restore());

describe("watchForEscapes", () => {
  it("has a working localStorage to watch", () => {
    escapes = watchForEscapes(() => ({}));
    expect(window.localStorage, "no localStorage — a leak into it would throw").toBeDefined();

    window.localStorage.setItem("pending-key", SECRET);

    expect(window.localStorage.getItem("pending-key")).toBe(SECRET);
    expect(escapes.all().filter((e) => e.includes(SECRET))).not.toEqual([]);
  });

  it("has a working sessionStorage to watch", () => {
    escapes = watchForEscapes(() => ({}));
    expect(window.sessionStorage).toBeDefined();

    window.sessionStorage.setItem("pending-key", SECRET);

    expect(escapes.all().filter((e) => e.includes(SECRET))).not.toEqual([]);
  });

  it("records an IndexedDB open", () => {
    escapes = watchForEscapes(() => ({}));
    expect(() => globalThis.indexedDB.open("keys")).toThrow();
    expect(escapes.indexedDb).toEqual(["keys"]);
  });

  it("records a request body", async () => {
    escapes = watchForEscapes(() => ({ ok: true }));
    await fetch("/api/v1/anything", { method: "POST", body: JSON.stringify({ k: SECRET }) });
    expect(escapes.all().filter((e) => e.includes(SECRET))).not.toEqual([]);
  });

  it("records a secret smuggled into a URL", async () => {
    escapes = watchForEscapes(() => ({ ok: true }));
    await fetch(`/api/v1/anything?k=${SECRET}`);
    expect(escapes.all().filter((e) => e.includes(SECRET))).not.toEqual([]);
  });

  it("stops watching once restored", () => {
    escapes = watchForEscapes(() => ({}));
    escapes.restore();
    escapes = watchForEscapes(() => ({}));

    // The previous run's wrapper must not still be stacked on the sink; if it
    // were, `restore` would be leaving instrumentation behind between tests.
    window.localStorage.setItem("a", "b");
    expect(escapes.storage).toEqual(["a=b"]);
  });
});
