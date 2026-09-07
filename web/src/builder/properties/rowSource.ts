/** Form IR §2.3: the one choice that decides a repeat's rows (scope §5). */

import { isExpr, type IrNode, type RepeatNode } from "@/builder/ir";

export type RowSourceKind = "count" | "enumerator" | "inline" | "dataset";

export const DATASET_SOURCE_NOTE =
  "Refused by the engine until _metadata.case_key exists (item 2) and a dataset version's row order survives delivery (known defect 16) — Form IR §2.3.";

export function rowSourceKind(node: RepeatNode): RowSourceKind {
  if (node.rowSource?.kind === "dataset") return "dataset";
  if (node.rowSource?.kind === "inline") return "inline";
  if (node.countExpr !== undefined) return "count";
  return "enumerator";
}

/** The node with exactly one source's keys. */
export function withRowSource(node: RepeatNode, kind: RowSourceKind): IrNode {
  const { countExpr: _count, rowSource: _source, ...rest } = node;
  switch (kind) {
    case "count":
      return {
        ...rest,
        countExpr: isExpr(node.countExpr)
          ? node.countExpr
          : { op: "lit", value: 1 },
      };
    case "inline":
      return {
        ...rest,
        rowSource:
          node.rowSource?.kind === "inline"
            ? node.rowSource
            : { kind: "inline", items: [] },
      };
    case "dataset":
      return node;
    case "enumerator":
      return rest;
  }
}
