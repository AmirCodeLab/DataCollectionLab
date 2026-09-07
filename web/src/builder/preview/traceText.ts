/** How one trace node reads on a line: its surface text, Appendix A's. */

import type { EngineValue, TraceNode } from "@/builder/engine/facade";

const SYMBOLS: Record<string, string> = {
  or: "or",
  and: "and",
  eq: "=",
  ne: "!=",
  lt: "<",
  lte: "<=",
  gt: ">",
  gte: ">=",
  add: "+",
  sub: "-",
  mul: "*",
  div: "div",
  mod: "mod",
  idiv: "idiv",
};

export function literalText(value: EngineValue): string {
  if (value === null) return "null()";
  if (value === true) return "true()";
  if (value === false) return "false()";
  if (typeof value === "number") return String(value);
  if (typeof value === "string") return `'${value}'`;
  return JSON.stringify(value);
}

/** The node's own line, with its children shown as their heads only. */
export function nodeText(node: TraceNode): string {
  switch (node.op) {
    case "lit":
      return literalText(node.literal ?? null);
    case "ref":
      return "${" + (node.path ?? "") + "}";
    case "call":
      return `${node.fn ?? "?"}(…)`;
    case "not":
      return "not(…)";
    case "neg":
      return "-…";
    case "if":
      return "if(…)";
    case "selected":
      return "selected(…)";
    case "in":
      return "in(…)";
    default:
      return SYMBOLS[node.op] ?? node.op;
  }
}

export function resultText(value: EngineValue): string {
  if (value === null) return "null";
  if (typeof value === "string") return `'${value}'`;
  if (typeof value === "boolean" || typeof value === "number")
    return String(value);
  return JSON.stringify(value);
}
