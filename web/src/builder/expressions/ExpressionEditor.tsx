/** An expression, edited as a visual term list or as code (scope §2).
 *
 * STUB — replaced in step 6. The contract is the props: the editor holds an
 * AST, emits an AST, and never round-trips through text on its own; text is
 * involved only while the author is looking at text, via
 * `POST /forms/expressions`.
 */

import type { Expr, FormIr } from "@/builder/ir";

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

export function ExpressionEditor({ label, value }: ExpressionEditorProps) {
  return (
    <div className="text-xs text-slate-500">
      {label}: {value === undefined ? "none" : JSON.stringify(value)}
    </div>
  );
}
