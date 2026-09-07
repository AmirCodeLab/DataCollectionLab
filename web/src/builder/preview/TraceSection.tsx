/** "Why is this question in the state it is in?" — the trace (scope §4).
 *
 * The AST of one of the selected question's expressions, each node annotated
 * with what it evaluated to against the answers entered in the preview. Null
 * is the usual answer to "why is this hidden": §4.4 propagates it and §4.7
 * widened it, so a reference to an unanswered question three screens back
 * hides a question exactly as thoroughly as `false` does, with no message
 * anywhere by design. The trace shows which node it was.
 *
 * The trace reports evaluation; it does not define it. Every value here is
 * the engine's, from `previewTrace`; this component only lays the tree out.
 */

import { useState } from "react";
import clsx from "clsx";

import type { TraceKey, TraceNode } from "@/builder/engine/facade";
import type { PreviewHandle } from "@/builder/engine/session";
import { nodeText, resultText } from "./traceText";

export interface TraceSectionProps {
  /** Where the engine keeps the question: `age`, or `members[i1].age`. */
  path: string;
  /** The expression keys this question actually has. */
  keys: TraceKey[];
  preview: PreviewHandle;
}

export function TraceSection({ path, keys, preview }: TraceSectionProps) {
  const [key, setKey] = useState<TraceKey | null>(keys[0] ?? null);
  const [trace, setTrace] = useState<{
    key: TraceKey;
    tree: TraceNode | null;
    error?: string;
  } | null>(null);

  if (keys.length === 0) return null;
  if (preview.status !== "ready") {
    return (
      <p className="text-xs text-slate-500">
        Open the preview to trace this question against answers.
      </p>
    );
  }
  const chosen: TraceKey = key ?? keys[0] ?? "relevant";

  const run = () => {
    preview.act((s) => {
      try {
        setTrace({ key: chosen, tree: s.trace(path, chosen) });
      } catch (cause: unknown) {
        setTrace({
          key: chosen,
          tree: null,
          error: cause instanceof Error ? cause.message : String(cause),
        });
      }
      return s.state();
    });
  };

  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-1">
          <span className="text-slate-600">Why is</span>
          <select
            aria-label="expression to trace"
            className="rounded border border-slate-300 px-1 py-0.5"
            value={chosen}
            onChange={(e) => setKey(e.target.value as TraceKey)}
          >
            {keys.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
          <span className="text-slate-600">what it is?</span>
        </label>
        <button
          type="button"
          className="rounded border border-slate-300 px-2 py-0.5 hover:bg-slate-50"
          onClick={run}
        >
          Trace
        </button>
      </div>
      {trace !== null && trace.error !== undefined && (
        <p className="text-red-700" role="alert">
          {trace.error}
        </p>
      )}
      {trace !== null && trace.tree !== null && (
        <ul className="font-mono" aria-label={`trace of ${trace.key}`}>
          <TraceLine node={trace.tree} depth={0} />
        </ul>
      )}
    </div>
  );
}

function TraceLine({ node, depth }: { node: TraceNode; depth: number }) {
  const isNull = node.result === null;
  return (
    <>
      <li
        className={clsx("flex gap-2 py-0.5", isNull && "bg-amber-50")}
        style={{ paddingInlineStart: `${String(depth)}rem` }}
      >
        <span className="text-slate-700">{nodeText(node)}</span>
        <span className="text-slate-400">→</span>
        <span
          className={clsx(
            isNull ? "font-semibold text-amber-800" : "text-slate-900",
          )}
        >
          {resultText(node.result)}
        </span>
      </li>
      {node.args.map((child, index) => (
        <TraceLine key={index} node={child} depth={depth + 1} />
      ))}
    </>
  );
}
