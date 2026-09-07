/** Opens the engine session for the document on this page and hands it down.
 *
 * The engine comes in as a prop — constructed by the page from `wasm.ts`, or
 * by a test from a fake — and is the only one the preview, the trace and test
 * mode will ever hold. */

import type { ReactNode } from "react";

import type { EngineModule } from "@/builder/engine/facade";
import { todayIso, usePreviewSession } from "@/builder/engine/session";
import { useBuilder } from "@/builder/store";
import { PreviewContext } from "./previewContext";

export function PreviewProvider({
  engine,
  children,
}: {
  engine: Promise<EngineModule>;
  children: ReactNode;
}) {
  const ir = useBuilder((s) => s.ir);
  const preview = usePreviewSession(engine, ir, todayIso());
  return (
    <PreviewContext.Provider value={preview}>
      {children}
    </PreviewContext.Provider>
  );
}
