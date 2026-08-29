/** Test environment setup.
 *
 * jsdom gives us a DOM and no crypto worth the name: `crypto.getRandomValues`
 * exists, `crypto.subtle` does not. The console's whole decryption path is
 * WebCrypto, so without a real SubtleCrypto these tests would exercise nothing
 * and pass. Node's own implementation is the real thing and supports X25519,
 * so it stands in for the browser's.
 */

import { webcrypto } from "node:crypto";
import "@testing-library/jest-dom/vitest";

if (globalThis.crypto?.subtle === undefined) {
  Object.defineProperty(globalThis, "crypto", {
    value: webcrypto,
    configurable: true,
    writable: true,
  });
}

/** A faithful-enough Storage, for when the environment does not supply one.
 *
 * This matters more than it looks. Under this jsdom, `window.localStorage`
 * reads back undefined, so code that writes a key to it THROWS. A test whose
 * job is to catch "the private key was written to localStorage" would then
 * pass — not because nothing was written, but because writing was impossible.
 * That is the worst kind of green: the leak test and the leak cancel out.
 *
 * So the sink is made to work, and `harness.watchForEscapes` records what goes
 * into it. `harness.test.ts` asserts both halves still function.
 *
 * Both sinks are replaced, not just the missing one. jsdom's own Storage is a
 * Proxy whose `set` trap turns any property assignment into a stored entry, so
 * `sessionStorage.setItem = spy` writes an item called "setItem" and leaves
 * the real method in place — instrumentation that silently records nothing.
 * A plain object behaves the way the wrapper in `harness` expects.
 */
function installStorage(name: "localStorage" | "sessionStorage"): void {
  const entries = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return entries.size;
    },
    key: (i: number) => [...entries.keys()][i] ?? null,
    getItem: (k: string) => entries.get(k) ?? null,
    setItem: (k: string, v: string) => void entries.set(String(k), String(v)),
    removeItem: (k: string) => void entries.delete(k),
    clear: () => entries.clear(),
  };

  for (const target of [globalThis, window]) {
    Object.defineProperty(target, name, {
      value: storage,
      configurable: true,
      writable: true,
    });
  }
}

installStorage("localStorage");
installStorage("sessionStorage");

// jsdom implements no IndexedDB at all, so an `indexedDB.open(...)` in the app
// would throw rather than be observed. A stub makes an attempt visible: the
// harness replaces `open` with a recorder and the test asserts it is never
// called.
if ((globalThis as Record<string, unknown>).indexedDB === undefined) {
  Object.defineProperty(globalThis, "indexedDB", {
    value: {
      open: () => {
        throw new Error("IndexedDB is not available in tests");
      },
    },
    configurable: true,
    writable: true,
  });
}
