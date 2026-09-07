/** The one constructor of the engine the console runs: the handset's Kotlin
 *  engine compiled to Wasm, fetched from where `scripts/build_engine_wasm.sh`
 *  put it. Nothing else in the console makes an engine, and nothing looks one
 *  up — the page constructs this and hands it down (PreviewProvider), so the
 *  preview, the trace and test mode can obtain a result from here and from
 *  nowhere else. That is the structural half of scope §2.1 ("preview runs
 *  the same engine the handset runs"): a fallback to server-side evaluation
 *  would need a second way in, and there is none to reach.
 */

import type { EngineModule } from "./facade";

/** Where `scripts/build_engine_wasm.sh` puts the module; served from `public/`. */
export const ENGINE_MODULE_URL =
  "/engine/DataCollectionLab-shared-form-engine.mjs";

/** Fetch the engine. Rejects when the bundle is not there — the preview says
 *  so rather than pretending.
 *
 * The URL is made absolute first. A bare `/engine/…mjs` is a path Vite's dev
 * server treats as source and refuses to serve from `public/` ("should not be
 * imported from source code"); an absolute URL is fetched by the browser
 * itself, which is what a static bundle wants in development and in the
 * built site alike. The module then finds its `.wasm` beside itself. */
export function loadWasmEngine(): Promise<EngineModule> {
  const url = new URL(ENGINE_MODULE_URL, globalThis.location.href).href;
  return import(/* @vite-ignore */ url).then(
    (mod: unknown) => mod as EngineModule,
  );
}
