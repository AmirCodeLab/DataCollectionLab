package com.dcp.form

/*
 * The engine's surface in a browser — the functions `web/src/builder/engine/
 * facade.ts` declares as `EngineModule`, and nothing else.
 *
 * This replaces the 2026-09-06 spike facade, whose caveat ("not an API") is
 * retired: this IS the API, and it is thin on purpose. Only primitives and
 * strings cross `@JsExport` on wasmJs, and `@JsExport` applies to functions
 * only, so the surface is a flat list of names taking and returning JSON
 * strings. Every rule is in [PreviewSession] (commonMain, tested on the JVM);
 * each function here is one line of delegation, so the Wasm build and the JVM
 * tests exercise the same code.
 */

@JsExport
fun engineVersion(): String = "form-engine wasm 0.1"

@JsExport
fun previewOpen(irJson: String, today: String): String = PreviewSessions.open(irJson, today)

@JsExport
fun previewClose(handle: String): String = PreviewSessions.close(handle)

@JsExport
fun previewState(handle: String): String = PreviewSessions.with(handle) { it.state() }

@JsExport
fun previewSet(handle: String, path: String, valueJson: String): String =
    PreviewSessions.with(handle) { it.set(path, valueJson) }

@JsExport
fun previewNext(handle: String): String = PreviewSessions.with(handle) { it.next() }

@JsExport
fun previewPrevious(handle: String): String = PreviewSessions.with(handle) { it.previous() }

@JsExport
fun previewEnter(handle: String, repeatId: String, instanceId: String): String =
    PreviewSessions.with(handle) { it.enter(repeatId, instanceId) }

@JsExport
fun previewLeave(handle: String): String = PreviewSessions.with(handle) { it.leave() }

@JsExport
fun previewAddRow(handle: String, repeatId: String): String =
    PreviewSessions.with(handle) { it.addRow(repeatId) }

@JsExport
fun previewDeleteRow(handle: String, repeatId: String, instanceId: String): String =
    PreviewSessions.with(handle) { it.deleteRow(repeatId, instanceId) }

@JsExport
fun previewGoToFirstBlocking(handle: String): String =
    PreviewSessions.with(handle) { it.goToFirstBlocking() }

@JsExport
fun previewTrace(handle: String, path: String, key: String): String =
    PreviewSessions.with(handle) { it.trace(path, key) }
