/** Opens the engine session for the document on this page and hands it down. */

import type { ReactNode } from "react";

import { todayIso, usePreviewSession } from "@/builder/engine/session";
import { useBuilder } from "@/builder/store";
import { PreviewContext } from "./previewContext";

export function PreviewProvider({ children }: { children: ReactNode }) {
  const ir = useBuilder((s) => s.ir);
  const preview = usePreviewSession(ir, todayIso());
  return (
    <PreviewContext.Provider value={preview}>
      {children}
    </PreviewContext.Provider>
  );
}
