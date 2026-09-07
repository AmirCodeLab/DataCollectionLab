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

import { useMemo, useState } from "react";
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

/** The trace is asked again for every state the engine returns — an answer
 *  typed in the preview changes what this question's relevance came to, and
 *  a tree that stood still would be a verdict on answers that no longer
 *  exist (the same rule as a publish refusal after an edit). */
export function TraceSection({ path, keys, preview }: TraceSectionProps) {
  const [key, setKey] = useState<TraceKey | null>(null);
  const chosen: TraceKey | null =
    key !== null && keys.includes(key) ? key : (keys[0] ?? null);
  const ready = preview.status === "ready" && preview.state !== null;
  // Re-run when the engine's state changes: `preview.state` is the object the
  // last operation returned, so it is the right key, and `trace` changes
  // nothing in the session.
  const state = preview.state;
  const trace = useMemo<{
    tree: TraceNode | null;
    error?: string;
  } | null>(() => {
    if (!ready || chosen === null) return null;
    try {
      return { tree: preview.trace(path, chosen) };
    } catch (cause: unknown) {
      return {
        tree: null,
        error: cause instanceof Error ? cause.message : String(cause),
      };
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `state` is the re-run key: a new state may change every result
  }, [ready, chosen, path, preview.trace, state]);

  if (keys.length === 0 || chosen === null) return null;
  if (!ready) {
    return (
      <p className="text-xs text-slate-500">
        The engine is loading; the trace follows the preview's answers.
      </p>
    );
  }

  return (
    <div className="space-y-2 text-xs" aria-label="trace">
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
        <span className="text-slate-600">
          what it is, against the preview's answers?
        </span>
      </label>
      {path.includes("[") && (
        <p className="text-slate-500">
          in row <code>{path}</code> — the one the preview is inside, or the
          first that exists
        </p>
      )}
      {trace?.error !== undefined && (
        <p className="text-red-700" role="alert">
          {trace.error}
        </p>
      )}
      {trace?.tree != null && (
        <ul className="font-mono" aria-label={`trace of ${chosen}`}>
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
