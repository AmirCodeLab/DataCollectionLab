/** The code rendering of an expression (Form IR Appendix A).
 *
 * Text is involved only while the author is looking at text. The AST is
 * rendered to canonical text by the server when this field opens, the author
 * edits, and what they typed is parsed by the server on a pause or on blur.
 * There is no parser and no printer here — `POST /forms/expressions` is the
 * one implementation, and scope §2.1 says a parser in the console is form
 * logic in the console.
 *
 * Rule 3 of the round trip: leaving the field with the text unchanged does
 * not re-parse. `settled` is the text the AST is known to mean — the
 * canonical text it rendered to, or the last text that parsed — and no
 * request goes out while the field still holds it.
 *
 * `doc` is the text *for* one AST object. When the AST the parent holds is
 * not the one `doc` is for, the field is between documents: empty and
 * settled if there is no AST, or waiting on the server's rendering if there
 * is. Nothing is derived from the AST locally.
 */

import { useEffect, useId, useRef, useState } from "react";

import { expressionText } from "@/api/queries";
import type { Expr, FormIr } from "@/builder/ir";
import { ReferencePicker } from "./ReferencePicker";

export const PARSE_DEBOUNCE_MS = 500;

export interface CodeFieldProps {
  value: Expr | undefined;
  onChange: (next: Expr | undefined) => void;
  ir: FormIr;
  nodeId: string;
  selfPath?: string;
  rowScope?: boolean;
  label: string;
}

interface Problem {
  message: string;
  /** Character the caret goes under; `null` is the whole expression. */
  offset: number | null;
}

interface Doc {
  /** The AST object this text is for. */
  for: Expr | undefined;
  text: string;
  /** The text `for` is known to mean; `null` when it has no text form. */
  settled: string | null;
  problem: Problem | null;
}

const NOTHING: Doc = { for: undefined, text: "", settled: "", problem: null };

export function CodeField({
  value,
  onChange,
  ir,
  nodeId,
  selfPath,
  rowScope,
  label,
}: CodeFieldProps) {
  const [doc, setDoc] = useState<Doc>(NOTHING);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inputId = useId();

  // What the field shows: its own document when it is for the AST the parent
  // holds; otherwise nothing yet (an absent AST is simply empty).
  const current: Doc = doc.for === value ? doc : { ...NOTHING, for: value };
  const rendering = value !== undefined && doc.for !== value;

  // Render the AST to canonical text when it changes from outside.
  useEffect(() => {
    if (value === undefined || doc.for === value) return;
    let cancelled = false;
    expressionText({ expression: value })
      .then((response) => {
        if (cancelled) return;
        if (typeof response.text === "string") {
          setDoc({
            for: value,
            text: response.text,
            settled: response.text,
            problem: null,
          });
        } else {
          // `in`, or a string holding both quote kinds: no surface form. The
          // AST is kept exactly as it is; the author is told why.
          setDoc({
            for: value,
            text: "",
            settled: null,
            problem: {
              message: response.error ?? "this expression has no text form",
              offset: null,
            },
          });
        }
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setDoc({
          for: value,
          text: "",
          settled: null,
          problem: {
            message: error instanceof Error ? error.message : String(error),
            offset: null,
          },
        });
      });
    return () => {
      cancelled = true;
    };
  }, [value, doc.for]);

  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const parse = (source: string): void => {
    if (timer.current !== null) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    if (source === current.settled) return;
    if (source.trim() === "") {
      // Clearing the field clears the property. An empty expression is
      // something the server refuses; here it means "none".
      setDoc(NOTHING);
      onChange(undefined);
      return;
    }
    expressionText({ text: source, selfPath, rowScope })
      .then((response) => {
        if (response.expression && typeof response.expression === "object") {
          const next = response.expression as Expr;
          // Claim the new AST before the parent hands it back, so it is not
          // re-rendered over the author's text.
          setDoc({ for: next, text: source, settled: source, problem: null });
          onChange(next);
        } else {
          setDoc((d) => ({
            ...d,
            for: value,
            text: source,
            problem: {
              message: response.error ?? "not an expression",
              offset:
                typeof response.offset === "number" ? response.offset : null,
            },
          }));
        }
      })
      .catch((error: unknown) => {
        setDoc((d) => ({
          ...d,
          for: value,
          text: source,
          problem: {
            message: error instanceof Error ? error.message : String(error),
            offset: null,
          },
        }));
      });
  };

  const edited = (next: string): void => {
    setDoc({ ...current, text: next });
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(() => parse(next), PARSE_DEBOUNCE_MS);
  };

  const insert = (path: string): void => {
    const element = textarea.current;
    const snippet = "${" + path + "}";
    if (element === null) {
      edited(current.text + snippet);
      return;
    }
    const start = element.selectionStart;
    const end = element.selectionEnd;
    edited(current.text.slice(0, start) + snippet + current.text.slice(end));
    // Put the caret after what was inserted, once React has the new text.
    requestAnimationFrame(() => {
      element.focus();
      element.setSelectionRange(start + snippet.length, start + snippet.length);
    });
  };

  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <label htmlFor={inputId} className="text-xs text-slate-600">
          {label} (code)
        </label>
        <ReferencePicker
          ir={ir}
          nodeId={nodeId}
          onPick={(entry) => insert(entry.path)}
        />
        {rendering && (
          <span className="text-xs text-slate-400">rendering…</span>
        )}
      </div>
      <textarea
        id={inputId}
        ref={textarea}
        value={current.text}
        onChange={(e) => edited(e.target.value)}
        onBlur={() => parse(current.text)}
        rows={2}
        spellCheck={false}
        aria-invalid={current.problem !== null}
        className="w-full rounded border border-slate-300 px-2 py-1 font-mono text-xs"
      />
      {current.problem !== null && (
        <Caret text={current.text} problem={current.problem} />
      )}
    </div>
  );
}

/** The message, and where in the text it is about. */
function Caret({ text, problem }: { text: string; problem: Problem }) {
  const at = problem.offset;
  return (
    <div role="alert" className="mt-1 text-xs text-red-700">
      {at !== null && at <= text.length && (
        <pre className="mb-0.5 overflow-x-auto font-mono text-slate-700">
          {text.slice(0, at)}
          <mark className="bg-red-200" data-testid="caret">
            {text.slice(at, at + 1) || " "}
          </mark>
          {text.slice(at + 1)}
        </pre>
      )}
      {problem.message}
    </div>
  );
}
