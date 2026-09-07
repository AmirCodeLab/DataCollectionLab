/** What the visual editor can show, read off the AST without changing it.
 *
 * Scope §2: the visual editor and the code field are two renderings of one
 * AST, and nothing is converted between them. So there is no visual "model"
 * here that the AST is turned into. A `TermView` is a *reading* of an
 * existing node — it keeps a reference to that node — and every edit produces
 * a new node for the one term it touched while the list keeps the other term
 * objects exactly as they were. That is what makes rules 1 and 2 checkable by
 * identity.
 *
 * Nothing here evaluates anything or decides what a form means.
 */

import type { Expr } from "@/builder/ir";

export const COMPARISONS = ["eq", "ne", "lt", "lte", "gt", "gte"] as const;
export type Comparison = (typeof COMPARISONS)[number];

export const COMPARISON_LABEL: Record<Comparison, string> = {
  eq: "=",
  ne: "≠",
  lt: "<",
  lte: "≤",
  gt: ">",
  gte: "≥",
};

/** A literal the visual editor can show: Form IR §2.1 scalar values plus
 *  null. Sequences, geopoints and media are code-only. */
export type Scalar = string | number | boolean | null;

export type Operand =
  { kind: "ref"; path: string } | { kind: "lit"; value: Scalar };

export type TermView =
  | { kind: "compare"; op: Comparison; ref: string; rhs: Operand }
  | { kind: "selected"; ref: string; value: Scalar }
  | { kind: "in"; ref: string; values: Scalar[] }
  | { kind: "null"; ref: string; isNull: boolean };

export interface Term {
  /** The node this is a reading of — the same object that sits in the AST. */
  node: Expr;
  negated: boolean;
  view: TermView;
}

export interface VisualReading {
  /** `null` for a single term. */
  junction: "and" | "or" | null;
  terms: Term[];
}

const isScalar = (value: unknown): value is Scalar =>
  value === null ||
  typeof value === "string" ||
  typeof value === "number" ||
  typeof value === "boolean";

const args = (node: Expr): Expr[] =>
  Array.isArray(node.args) ? (node.args as Expr[]) : [];

const refPath = (node: Expr | undefined): string | null =>
  node !== undefined && node.op === "ref" && typeof node.path === "string"
    ? node.path
    : null;

function operand(node: Expr | undefined): Operand | null {
  if (node === undefined) return null;
  const path = refPath(node);
  if (path !== null) return { kind: "ref", path };
  if (node.op === "lit" && isScalar(node.value)) {
    return { kind: "lit", value: node.value };
  }
  return null;
}

function readTermView(node: Expr): TermView | null {
  const list = args(node);
  if ((COMPARISONS as readonly string[]).includes(node.op)) {
    if (list.length !== 2) return null;
    const ref = refPath(list[0]);
    const rhs = operand(list[1]);
    if (ref === null || rhs === null) return null;
    return { kind: "compare", op: node.op as Comparison, ref, rhs };
  }
  if (node.op === "selected") {
    if (list.length !== 2) return null;
    const ref = refPath(list[0]);
    const value = list[1];
    if (ref === null || value.op !== "lit" || !isScalar(value.value))
      return null;
    return { kind: "selected", ref, value: value.value };
  }
  if (node.op === "in") {
    if (list.length !== 2) return null;
    const ref = refPath(list[0]);
    const haystack = list[1];
    if (
      ref === null ||
      haystack.op !== "lit" ||
      !Array.isArray(haystack.value)
    ) {
      return null;
    }
    const values = haystack.value as unknown[];
    if (!values.every(isScalar)) return null;
    return { kind: "in", ref, values };
  }
  if (
    node.op === "call" &&
    (node.fn === "is_null" || node.fn === "is_not_null")
  ) {
    if (list.length !== 1) return null;
    const ref = refPath(list[0]);
    if (ref === null) return null;
    return { kind: "null", ref, isNull: node.fn === "is_null" };
  }
  return null;
}

/** One term, possibly under a `not`. */
export function readTerm(node: Expr): Term | null {
  if (node.op === "not") {
    const inner = args(node);
    if (inner.length !== 1) return null;
    const view = readTermView(inner[0]);
    return view === null ? null : { node, negated: true, view };
  }
  const view = readTermView(node);
  return view === null ? null : { node, negated: false, view };
}

/** The visual reading of an expression, or `null` when it is beyond the
 *  visual editor — nested and/or, arithmetic, a call, anything else — in
 *  which case the code field is the only rendering. */
export function readVisual(node: Expr): VisualReading | null {
  if (node.op === "and" || node.op === "or") {
    const list = args(node);
    if (list.length < 2) return null;
    const terms: Term[] = [];
    for (const item of list) {
      const term = readTerm(item);
      if (term === null) return null;
      terms.push(term);
    }
    return { junction: node.op, terms };
  }
  const term = readTerm(node);
  return term === null ? null : { junction: null, terms: [term] };
}

// --- Building a term from a view --------------------------------------------

const ref = (path: string): Expr => ({ op: "ref", path });
const lit = (value: Scalar | Scalar[]): Expr => ({ op: "lit", value });

function operandNode(value: Operand): Expr {
  return value.kind === "ref" ? ref(value.path) : lit(value.value);
}

function viewNode(view: TermView): Expr {
  switch (view.kind) {
    case "compare":
      return { op: view.op, args: [ref(view.ref), operandNode(view.rhs)] };
    case "selected":
      return { op: "selected", args: [ref(view.ref), lit(view.value)] };
    case "in":
      return { op: "in", args: [ref(view.ref), lit(view.values)] };
    case "null":
      return {
        op: "call",
        fn: view.isNull ? "is_null" : "is_not_null",
        args: [ref(view.ref)],
      };
  }
}

/** A fresh node for an edited term. Only ever called for the term the author
 *  touched; the other terms are not rebuilt. */
export function termNode(negated: boolean, view: TermView): Expr {
  const node = viewNode(view);
  return negated ? { op: "not", args: [node] } : node;
}

/** The expression for a term list. A single term is the term itself, not an
 *  `and` of one — §4.1's and/or take two or more arguments. */
export function visualNode(
  junction: "and" | "or",
  terms: Expr[],
): Expr | undefined {
  if (terms.length === 0) return undefined;
  if (terms.length === 1) return terms[0];
  return { op: junction, args: terms };
}

export const DEFAULT_TERM: TermView = {
  kind: "compare",
  op: "eq",
  ref: "",
  rhs: { kind: "lit", value: "" },
};

/** A number literal as text: every digit, never rounded (Appendix A.4).
 *
 * `String` gives the shortest digits that read back as the same value —
 * `0.30000000000000004` stays seventeen digits. The one spelling JSON loses is
 * `800.0` versus `800`, which arrives here as the number 800; A.4 says why
 * that is harmless (both engines compare them equal, integer-typed arguments
 * accept a whole-valued decimal).
 */
export const numberText = (value: number): string => String(value);

/** The author's number, or `null` for anything that is not a finite one. */
export function parseNumber(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") return null;
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}
