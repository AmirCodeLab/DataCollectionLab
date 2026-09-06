/** The visual rendering of an expression: a list of terms, all-and or all-or.
 *
 * It emits AST directly and never text (rule 4), and an edit rebuilds only
 * the term it touched (rule 2): `terms` holds the very node objects from the
 * AST, and the one the author changed is replaced in that list by a fresh
 * node while the others are passed through untouched.
 */

import { useId } from "react";

import type { Expr, FormIr } from "@/builder/ir";
import { ReferenceSelect } from "./ReferencePicker";
import {
  COMPARISON_LABEL,
  COMPARISONS,
  DEFAULT_TERM,
  numberText,
  parseNumber,
  termNode,
  visualNode,
  type Comparison,
  type Operand,
  type Scalar,
  type Term,
  type TermView,
  type VisualReading,
} from "./shapes";

export interface VisualEditorProps {
  reading: VisualReading | null;
  onChange: (next: Expr | undefined) => void;
  ir: FormIr;
  nodeId: string;
}

export function VisualEditor({
  reading,
  onChange,
  ir,
  nodeId,
}: VisualEditorProps) {
  const terms: Term[] = reading?.terms ?? [];
  const junction = reading?.junction ?? "and";
  const nodes = terms.map((t) => t.node);

  const emit = (next: Expr[], nextJunction: "and" | "or"): void => {
    onChange(visualNode(nextJunction, next));
  };

  const replace = (index: number, negated: boolean, view: TermView): void => {
    const next = [...nodes];
    next[index] = termNode(negated, view);
    emit(next, junction);
  };

  const remove = (index: number): void => {
    emit(
      nodes.filter((_, i) => i !== index),
      junction,
    );
  };

  const add = (): void => {
    emit([...nodes, termNode(false, DEFAULT_TERM)], junction);
  };

  return (
    <div className="space-y-1">
      {terms.length > 1 && (
        <div className="flex items-center gap-2 text-xs text-slate-600">
          <span>Every term must hold</span>
          <select
            aria-label="all or any"
            value={junction}
            onChange={(e) =>
              emit(nodes, e.target.value === "or" ? "or" : "and")
            }
            className="rounded border border-slate-300 bg-white px-1 py-0.5"
          >
            <option value="and">all of them (and)</option>
            <option value="or">any of them (or)</option>
          </select>
        </div>
      )}
      <ol className="space-y-1">
        {terms.map((term, index) => (
          <li key={index} className="flex flex-wrap items-center gap-1">
            <TermRow
              term={term}
              ir={ir}
              nodeId={nodeId}
              onChange={(negated, view) => replace(index, negated, view)}
            />
            <button
              type="button"
              onClick={() => remove(index)}
              aria-label={`remove term ${String(index + 1)}`}
              className="ms-auto rounded px-1 text-xs text-slate-500 hover:bg-slate-100"
            >
              ×
            </button>
          </li>
        ))}
      </ol>
      <button
        type="button"
        onClick={add}
        className="rounded border border-slate-300 bg-white px-2 py-0.5 text-xs hover:bg-slate-50"
      >
        + term
      </button>
    </div>
  );
}

type TermKind = TermView["kind"];

const KIND_LABEL: Record<TermKind, string> = {
  compare: "compares",
  selected: "has selected",
  in: "is one of",
  null: "is empty / not empty",
};

/** A view of the same kind with the reference carried over. */
function retarget(kind: TermKind, from: TermView): TermView {
  switch (kind) {
    case "compare":
      return { kind, op: "eq", ref: from.ref, rhs: { kind: "lit", value: "" } };
    case "selected":
      return { kind, ref: from.ref, value: "" };
    case "in":
      return { kind, ref: from.ref, values: [] };
    case "null":
      return { kind, ref: from.ref, isNull: true };
  }
}

function TermRow({
  term,
  ir,
  nodeId,
  onChange,
}: {
  term: Term;
  ir: FormIr;
  nodeId: string;
  onChange: (negated: boolean, view: TermView) => void;
}) {
  const { negated, view } = term;
  const set = (next: TermView) => onChange(negated, next);

  return (
    <>
      <label className="flex items-center gap-1 text-xs text-slate-600">
        <input
          type="checkbox"
          checked={negated}
          onChange={(e) => onChange(e.target.checked, view)}
        />
        not
      </label>
      <ReferenceSelect
        ir={ir}
        nodeId={nodeId}
        value={view.ref}
        onChange={(ref) => set({ ...view, ref })}
        ariaLabel="field"
      />
      <select
        aria-label="term kind"
        value={view.kind}
        onChange={(e) => set(retarget(e.target.value as TermKind, view))}
        className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
      >
        {(Object.keys(KIND_LABEL) as TermKind[]).map((kind) => (
          <option key={kind} value={kind}>
            {KIND_LABEL[kind]}
          </option>
        ))}
      </select>
      {view.kind === "compare" && (
        <>
          <select
            aria-label="comparison"
            value={view.op}
            onChange={(e) => set({ ...view, op: e.target.value as Comparison })}
            className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
          >
            {COMPARISONS.map((op) => (
              <option key={op} value={op}>
                {COMPARISON_LABEL[op]}
              </option>
            ))}
          </select>
          <OperandInput
            value={view.rhs}
            onChange={(rhs) => set({ ...view, rhs })}
            ir={ir}
            nodeId={nodeId}
          />
        </>
      )}
      {view.kind === "selected" && (
        <ScalarInput
          value={view.value}
          onChange={(value) => set({ ...view, value })}
        />
      )}
      {view.kind === "in" && (
        <ListInput
          values={view.values}
          onChange={(values) => set({ ...view, values })}
        />
      )}
      {view.kind === "null" && (
        <select
          aria-label="empty or not"
          value={view.isNull ? "null" : "not-null"}
          onChange={(e) => set({ ...view, isNull: e.target.value === "null" })}
          className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
        >
          <option value="null">is empty</option>
          <option value="not-null">is not empty</option>
        </select>
      )}
    </>
  );
}

function OperandInput({
  value,
  onChange,
  ir,
  nodeId,
}: {
  value: Operand;
  onChange: (next: Operand) => void;
  ir: FormIr;
  nodeId: string;
}) {
  return (
    <>
      <select
        aria-label="compare against"
        value={value.kind}
        onChange={(e) =>
          onChange(
            e.target.value === "ref"
              ? { kind: "ref", path: "" }
              : { kind: "lit", value: "" },
          )
        }
        className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
      >
        <option value="lit">a value</option>
        <option value="ref">another field</option>
      </select>
      {value.kind === "ref" ? (
        <ReferenceSelect
          ir={ir}
          nodeId={nodeId}
          value={value.path}
          onChange={(path) => onChange({ kind: "ref", path })}
          ariaLabel="other field"
        />
      ) : (
        <ScalarInput
          value={value.value}
          onChange={(v) => onChange({ kind: "lit", value: v })}
        />
      )}
    </>
  );
}

type ScalarKind = "text" | "number" | "true" | "false" | "null";

const scalarKind = (value: Scalar): ScalarKind =>
  value === null
    ? "null"
    : typeof value === "number"
      ? "number"
      : typeof value === "boolean"
        ? value
          ? "true"
          : "false"
        : "text";

/** One literal. A number is shown with every digit (A.4) and read with
 *  `Number`; anything that is not a finite number is refused, keeping the
 *  value that was there. */
function ScalarInput({
  value,
  onChange,
}: {
  value: Scalar;
  onChange: (next: Scalar) => void;
}) {
  const kind = scalarKind(value);
  const hint = useId();
  return (
    <>
      <select
        aria-label="value type"
        value={kind}
        onChange={(e) => {
          const next = e.target.value as ScalarKind;
          if (next === "null") onChange(null);
          else if (next === "true") onChange(true);
          else if (next === "false") onChange(false);
          else if (next === "number")
            onChange(typeof value === "number" ? value : 0);
          else onChange(typeof value === "string" ? value : "");
        }}
        className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs"
      >
        <option value="text">text</option>
        <option value="number">number</option>
        <option value="true">yes (true)</option>
        <option value="false">no (false)</option>
        <option value="null">empty (null)</option>
      </select>
      {kind === "text" && (
        <input
          aria-label="value"
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="rounded border border-slate-300 px-1 py-0.5 text-xs"
        />
      )}
      {kind === "number" && (
        <NumberInput
          value={typeof value === "number" ? value : 0}
          onChange={onChange}
          describedBy={hint}
        />
      )}
    </>
  );
}

function NumberInput({
  value,
  onChange,
  describedBy,
}: {
  value: number;
  onChange: (next: number) => void;
  describedBy: string;
}) {
  const parsed = parseNumber;
  return (
    <input
      aria-label="value"
      aria-describedby={describedBy}
      inputMode="decimal"
      defaultValue={numberText(value)}
      key={numberText(value)}
      onBlur={(e) => {
        const next = parsed(e.target.value);
        if (next === null) {
          e.target.value = numberText(value);
          return;
        }
        if (next !== value) onChange(next);
      }}
      className="w-40 rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
    />
  );
}

/** The values of an `in` — one per line, each read as a number where it
 *  parses as one and as text otherwise; `null` and booleans are code-only. */
function ListInput({
  values,
  onChange,
}: {
  values: Scalar[];
  onChange: (next: Scalar[]) => void;
}) {
  const shown = values
    .map((v) =>
      v === null ? "" : typeof v === "number" ? numberText(v) : String(v),
    )
    .join("\n");
  return (
    <textarea
      aria-label="values, one per line"
      defaultValue={shown}
      key={shown}
      rows={Math.max(2, Math.min(6, values.length))}
      onBlur={(e) => {
        const lines = e.target.value
          .split("\n")
          .filter((line) => line.trim() !== "");
        const next: Scalar[] = lines.map((line) => parseNumber(line) ?? line);
        if (JSON.stringify(next) !== JSON.stringify(values)) onChange(next);
      }}
      className="rounded border border-slate-300 px-1 py-0.5 font-mono text-xs"
    />
  );
}
