/** Where the page keeps its one engine session (scope §4).
 *
 * The session lives with the page, not with the preview pane: the trace in
 * the properties pane asks the same session "why is this question hidden?",
 * and the answer only means something against the answers the preview
 * entered. One session, so the two agree; kept while the pane is closed, so
 * an author can close the preview, look at a question's properties, and
 * trace it against what they had just typed. (A context and a hook in their
 * own module: a file that exports a component cannot also export these and
 * still hot-reload — see lib/autoRefresh.ts.)
 */

import { createContext, useContext } from "react";

import type { PreviewHandle } from "@/builder/engine/session";

export const PreviewContext = createContext<PreviewHandle | null>(null);

/** The page's engine session, or null outside a builder page. */
export function usePreview(): PreviewHandle | null {
  return useContext(PreviewContext);
}
