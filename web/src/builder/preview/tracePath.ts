/** What the trace is asked about: which expressions, and at which path.
 *
 * Outside a repeat the path is the id. Inside one, a question has a value per
 * row, so the row is the one the preview is currently inside — an author who
 * opened Father in the preview and asks why `age` is hidden is asking about
 * Father's — and, outside any row, the first row that exists. With no rows
 * at all there is nothing to trace, and the caller says so rather than
 * asking the engine to evaluate a row that is not there.
 */

import type { TraceKey } from "@/builder/engine/facade";
import type { PreviewHandle } from "@/builder/engine/session";
import { find, isExpr, type FormIr, type QuestionNode } from "@/builder/ir";

const QUESTION_KEYS: TraceKey[] = [
  "relevant",
  "constraint",
  "calculate",
  "required",
  "readOnly",
  "default",
];

/** The expression keys this question carries, in the panel's order. */
export function questionTraceKeys(node: QuestionNode): TraceKey[] {
  return QUESTION_KEYS.filter((key) => isExpr(node[key]));
}

/** The engine path for this question given where the preview is, or the
 *  repeat it sits in when that repeat has no rows yet. */
export function tracePath(
  ir: FormIr,
  id: string,
  state: PreviewHandle["state"],
): { path: string } | { noRowsIn: string } {
  const repeat = find(ir, id)?.repeat ?? null;
  if (repeat === null) return { path: id };
  if (state?.inside?.repeatId === repeat.id) {
    return { path: `${repeat.id}[${state.inside.instanceId}].${id}` };
  }
  const prefix = `${repeat.id}[`;
  const first = Object.keys(state?.relevant ?? {}).find(
    (p) => p.startsWith(prefix) && p.endsWith(`].${id}`),
  );
  if (first === undefined) return { noRowsIn: repeat.id };
  return { path: first };
}
