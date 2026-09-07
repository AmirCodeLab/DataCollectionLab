#!/bin/sh
# build_engine_wasm.sh — the engine, compiled to Wasm, where the console loads it.
#
# The builder's preview runs the same engine the handset runs (item 0's second
# binding decision; docs/wasm-spike.md option (a)). This builds the wasmJs
# target and copies the browser bundle into web/public/engine/, which Vite
# serves at /engine/ and web/src/builder/engine/facade.ts imports at runtime.
#
# The bundle is a build output and is not committed (web/.gitignore). Run this
# before `npm run dev` or `npm run build` in web/ whenever the engine changes.
set -eu
cd "$(dirname "$0")/.."

# The optimised ES-module set, not the webpack distribution: the console
# imports the `.mjs` at runtime (facade.ts), and the webpack bundle is a
# script with no exports. `optimized/` is binaryen's output (~470 KB raw,
# ~130 KB brotli per docs/wasm-spike.md) beside its glue.
./gradlew :shared:form-engine:compileProductionExecutableKotlinWasmJsOptimize -q

SRC=shared/form-engine/build/compileSync/wasmJs/main/productionExecutable/optimized
DEST=web/public/engine
mkdir -p "$DEST"
rm -f "$DEST"/DataCollectionLab-shared-form-engine.*
cp "$SRC"/DataCollectionLab-shared-form-engine.* "$DEST"/
ls -la "$DEST"
