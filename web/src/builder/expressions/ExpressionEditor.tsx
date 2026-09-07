/** An expression, edited as a visual term list or as code (scope §2).
 *
 * Two renderings of one AST, and nothing is ever converted between them. The
 * editor decides which rendering to show and shows it:
 *
 * - **Load never mutates.** Opening with an AST emits nothing. The visual
 *   reading is computed from the AST on every render and holds the AST's own
 *   node objects; the code field asks the server for the canonical text and
 *   emits nothing until the author types.
 * - **A visual edit rebuilds only the term it touched** — `VisualEditor`.
 * - **Leaving the code field unchanged does not re-parse** — `CodeField`.
 * - **The visual editor never round-trips through text** — it emits AST.
 *
 * An AST beyond the visual shapes (nested and/or, arithmetic, a call other
 * than `is_null`/`is_not_null`) is shown as code, with a note. There is no
 * "convert to visual" button: a button that rewrites an author's expression
 * into a shape the builder prefers is the whole bug.
 */

import { useState } from "react";
import clsx from "clsx";

import type { Expr, FormIr } from "@/builder/ir";
import { CodeField } from "./CodeField";
import { readVisual } from "./shapes";
import { VisualEditor } from "./VisualEditor";

export interface ExpressionEditorProps {
  /** The AST, or nothing. */
  value: Expr | undefined;
  /** Emits the AST directly. `undefined` clears the property. */
  onChange: (next: Expr | undefined) => void;
  /** The document and the node the expression belongs to — what the picker
   *  needs to group references by where the author is. */
  ir: FormIr;
  nodeId: string;
  /** For a constraint: what `.` refers to. */
  selfPath?: string;
  /** For a choice filter: a bare name is a candidate row's column. */
  rowScope?: boolean;
  label: string;
}

export const BEYOND_VISUAL =
  "This expression is beyond the visual editor; edit it as code.";

type Mode = "visual" | "code";

export function ExpressionEditor(props: ExpressionEditorProps) {
  const { value, onChange, ir, nodeId, selfPath, rowScope, label } = props;
  const reading = value === undefined ? null : readVisual(value);
  const fits = value === undefined || reading !== null;
  const [chosen, setChosen] = useState<Mode>(fits ? "visual" : "code");
  const mode: Mode = fits ? chosen : "code";

  return (
    <fieldset className="rounded border border-slate-200 p-2">
      <legend className="px-1 text-xs font-medium text-slate-700">
        {label}
      </legend>
      <div
        className="mb-2 flex items-center gap-1 text-xs"
        role="tablist"
        aria-label={`${label} rendering`}
      >
        <ModeButton
          active={mode === "visual"}
          disabled={!fits}
          onClick={() => setChosen("visual")}
        >
          Visual
        </ModeButton>
        <ModeButton active={mode === "code"} onClick={() => setChosen("code")}>
          Code
        </ModeButton>
        {!fits && <span className="ms-2 text-slate-500">{BEYOND_VISUAL}</span>}
      </div>
      {mode === "visual" ? (
        <VisualEditor
          reading={reading}
          onChange={onChange}
          ir={ir}
          nodeId={nodeId}
        />
      ) : (
        <CodeField
          value={value}
          onChange={onChange}
          ir={ir}
          nodeId={nodeId}
          selfPath={selfPath}
          rowScope={rowScope}
          label={label}
        />
      )}
    </fieldset>
  );
}

function ModeButton({
  active,
  disabled,
  onClick,
  children,
}: {
  active: boolean;
  disabled?: boolean;
  onClick: () => void;
  children: string;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      disabled={disabled}
      onClick={onClick}
      className={clsx(
        "rounded px-2 py-0.5",
        active ? "bg-slate-900 text-white" : "border border-slate-300 bg-white",
        disabled && "opacity-50",
      )}
    >
      {children}
    </button>
  );
}
