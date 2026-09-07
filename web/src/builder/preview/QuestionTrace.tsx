/** The trace, mounted on a selected node's properties (scope §4).
 *
 * What is traced is decided here and nowhere else: which of the node's
 * expressions exist, and which *path* in the engine stands for this
 * question. Outside a repeat the path is the id. Inside one, a question has
 * a value per row, so the row is the one the preview is currently inside —
 * an author who opened Father in the preview and asks why `age` is hidden is
 * asking about Father's — and, outside any row, the first row that exists.
 * With no rows at all there is nothing to trace, and it says so rather than
 * asking the engine to evaluate a row that is not there.
 */

import {
  isExpr,
  type FormIr,
  type QuestionNode,
  type RepeatNode,
} from "@/builder/ir";
import { usePreview } from "./previewContext";
import { questionTraceKeys, tracePath } from "./tracePath";
import { TraceSection } from "./TraceSection";

export function QuestionTrace({
  ir,
  node,
}: {
  ir: FormIr;
  node: QuestionNode;
}) {
  const preview = usePreview();
  const keys = questionTraceKeys(node);
  if (preview === null || keys.length === 0) return null;
  const where = tracePath(ir, node.id, preview.state);
  if ("noRowsIn" in where) {
    return (
      <p className="text-xs text-slate-500">
        Add a row to <code>{where.noRowsIn}</code> in the preview to trace this
        question in it.
      </p>
    );
  }
  return <TraceSection path={where.path} keys={keys} preview={preview} />;
}

/** A repeat's own expression is its count (§2.3); it is traced by its id. */
export function RepeatTrace({ node }: { node: RepeatNode }) {
  const preview = usePreview();
  if (preview === null || !isExpr(node.countExpr)) return null;
  return <TraceSection path={node.id} keys={["countExpr"]} preview={preview} />;
}
