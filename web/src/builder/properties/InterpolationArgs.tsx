/** The arguments a `{0}` slot is filled from (Form IR §7.1).
 *
 * `labelArgs`, `constraintMessageArgs` and a repeat's `summaryLabelArgs` were
 * the last properties in the IR with no editor. The label field said so —
 * "{0}, {1} slots interpolate labelArgs, edited as IR (§7.1)" — which is an
 * honest sentence and not a feature. Building a real MICS6 module made the cost
 * concrete: **twelve of its twenty questions write `(name)` and mean the
 * member's name**, so without this the most common pattern in household
 * listing instruments reaches an enumerator as literal parentheses
 * (`docs/builder-audit-2026-09-13.md` §4).
 *
 * ## One parser, and it is not here
 *
 * Two rules shape this component, and both are about staying out of the way.
 *
 * **It emits AST and never text.** Each argument is an `ExpressionEditor` —
 * the same component the `relevant` and `constraint` fields use, visual or
 * code, with the server parsing the code half through `POST /forms/expressions`.
 * A second path into `labelArgs` would be a second parser, and the shape it
 * would get subtly wrong is the shape nobody checks.
 *
 * **It does not read the slots.** Nothing here parses `{0}` out of the label.
 * That grammar has an escape (`{{`) and belongs to the engine, which already
 * owns it in `text.slot_indices`; a copy here would drift on the first corner
 * case. So the editor shows one row per argument that exists and a button to
 * add another, and the **server** says when a slot has no argument behind it —
 * a §10.3 warning that arrives through the same compile round trip as every
 * other diagnostic and is rendered in the plan pane.
 *
 * That division is why the two halves cannot disagree: the console never forms
 * an opinion about either the expression or the slot.
 *
 * ## Removing an argument renumbers the slots after it
 *
 * `{1}` becomes `{0}` when the first argument goes, and the template is not
 * rewritten — it cannot be, because the same arguments are shared across every
 * translation and a translator may have reordered them (§7.1). The control
 * says so rather than guessing, and the server's warning catches the case where
 * the author does not act on it.
 */

import type { Expr, FormIr } from "@/builder/ir";
import { ExpressionEditor } from "@/builder/expressions/ExpressionEditor";

export interface InterpolationArgsProps {
  ir: FormIr;
  /** The node the arguments belong to — what the reference picker groups by. */
  nodeId: string;
  /** What the property is called in the IR, for the hint. */
  argsKey: "labelArgs" | "constraintMessageArgs" | "summaryLabelArgs";
  /** What it fills, for the hint. */
  fills: string;
  value: Expr[] | undefined;
  onChange: (next: Expr[] | undefined) => void;
}

/** An argument that has been added and not yet given an expression. */
const EMPTY: Expr = { op: "lit", value: "" };

export function InterpolationArgs(props: InterpolationArgsProps) {
  const { ir, nodeId, argsKey, fills, value, onChange } = props;
  const args = value ?? [];

  const emit = (next: Expr[]) => onChange(next.length === 0 ? undefined : next);

  return (
    <fieldset className="rounded border border-slate-200 px-2 pb-2 pt-1">
      <legend className="px-1 text-xs font-medium text-slate-600">
        {argsKey}
      </legend>
      <p className="text-[11px] text-slate-500">
        Fills the {fills}&rsquo;s <code>{"{0}"}</code>, <code>{"{1}"}</code> …
        slots, in order, in every language (§7.1).
      </p>
      {args.length === 0 && (
        <p className="mt-1 text-[11px] text-slate-500">
          None. A <code>{"{0}"}</code> in the text with nothing here is shown to
          a respondent as written.
        </p>
      )}
      <ol className="mt-1 space-y-2">
        {args.map((arg, index) => (
          <li key={index} className="rounded bg-slate-50 p-2">
            <div className="flex items-start gap-2">
              <span className="mt-1 font-mono text-xs text-slate-600">
                {`{${index}}`}
              </span>
              <div className="min-w-0 grow">
                <ExpressionEditor
                  value={arg}
                  onChange={(next) => {
                    const copy = [...args];
                    copy[index] = next ?? EMPTY;
                    emit(copy);
                  }}
                  ir={ir}
                  nodeId={nodeId}
                  label={`${argsKey} ${index}`}
                />
              </div>
              <button
                type="button"
                aria-label={`remove ${argsKey} argument ${index}`}
                title="Removing this renumbers the slots after it; the text is not rewritten"
                className="mt-0.5 rounded px-1 text-sm text-slate-500 hover:bg-slate-200"
                onClick={() => emit(args.filter((_, i) => i !== index))}
              >
                ×
              </button>
            </div>
          </li>
        ))}
      </ol>
      <button
        type="button"
        // A question carries two of these — `labelArgs` and
        // `constraintMessageArgs` — so "add argument" alone is two controls
        // with one name. The accessible name says which.
        aria-label={`add argument to ${argsKey}`}
        className="mt-2 rounded border border-slate-300 px-2 py-0.5 text-xs"
        onClick={() => emit([...args, EMPTY])}
      >
        add argument
      </button>
      {args.length > 1 && (
        <p className="mt-1 text-[11px] text-slate-500">
          Removing an argument renumbers the ones after it. The text is not
          rewritten: the same arguments are shared across translations and a
          translator may have reordered the slots.
        </p>
      )}
    </fieldset>
  );
}
