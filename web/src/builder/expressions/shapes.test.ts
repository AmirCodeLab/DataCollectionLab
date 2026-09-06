/** Reading an AST for the visual editor, and building the one term an edit
 *  touched. */

import { describe, expect, it } from "vitest";

import type { Expr } from "@/builder/ir";
import {
  numberText,
  parseNumber,
  readVisual,
  termNode,
  visualNode,
} from "./shapes";

const ref = (path: string): Expr => ({ op: "ref", path });
const lit = (value: unknown): Expr => ({ op: "lit", value });

describe("readVisual", () => {
  it("reads the shapes §2 lists, keeping the term nodes by identity", () => {
    const a: Expr = { op: "gte", args: [ref("age"), lit(18)] };
    const b: Expr = { op: "selected", args: [ref("consent"), lit("yes")] };
    const c: Expr = {
      op: "not",
      args: [{ op: "call", fn: "is_null", args: [ref("name")] }],
    };
    const d: Expr = { op: "in", args: [ref("size"), lit([1, 2, 3])] };
    const e: Expr = { op: "eq", args: [ref("a"), ref("b")] };
    const reading = readVisual({ op: "and", args: [a, b, c, d, e] });
    expect(reading?.junction).toBe("and");
    expect(reading?.terms.map((t) => t.node)).toEqual([a, b, c, d, e]);
    expect(reading?.terms[0].node).toBe(a);
    expect(reading?.terms[2]).toMatchObject({
      negated: true,
      view: { kind: "null", ref: "name", isNull: true },
    });
    expect(reading?.terms[3].view).toEqual({
      kind: "in",
      ref: "size",
      values: [1, 2, 3],
    });
    expect(reading?.terms[4].view).toMatchObject({
      rhs: { kind: "ref", path: "b" },
    });
  });

  it("reads a single term as a list of one with no junction", () => {
    const only: Expr = { op: "lt", args: [ref("age"), lit(5)] };
    expect(readVisual(only)).toEqual({
      junction: null,
      terms: [
        {
          node: only,
          negated: false,
          view: {
            kind: "compare",
            op: "lt",
            ref: "age",
            rhs: { kind: "lit", value: 5 },
          },
        },
      ],
    });
  });

  it("is null for anything beyond the visual shapes, rather than approximating", () => {
    const nested: Expr = {
      op: "and",
      args: [
        { op: "or", args: [ref("a"), ref("b")] },
        { op: "eq", args: [ref("a"), lit(1)] },
      ],
    };
    expect(readVisual(nested)).toBeNull();
    expect(
      readVisual({
        op: "eq",
        args: [{ op: "add", args: [ref("a"), lit(1)] }, lit(2)],
      }),
    ).toBeNull();
    expect(
      readVisual({ op: "call", fn: "count", args: [ref("members[].name")] }),
    ).toBeNull();
    expect(readVisual({ op: "eq", args: [lit(1), ref("a")] })).toBeNull();
    expect(readVisual({ op: "and", args: [ref("a")] })).toBeNull();
    expect(
      readVisual({ op: "not", args: [{ op: "not", args: [ref("a")] }] }),
    ).toBeNull();
  });
});

describe("building", () => {
  it("makes exactly the §4.1 node for a view", () => {
    expect(
      termNode(false, {
        kind: "compare",
        op: "ne",
        ref: "a",
        rhs: { kind: "lit", value: null },
      }),
    ).toEqual({
      op: "ne",
      args: [ref("a"), lit(null)],
    });
    expect(termNode(true, { kind: "null", ref: "a", isNull: false })).toEqual({
      op: "not",
      args: [{ op: "call", fn: "is_not_null", args: [ref("a")] }],
    });
    expect(termNode(false, { kind: "in", ref: "a", values: ["x", 2] })).toEqual(
      {
        op: "in",
        args: [ref("a"), lit(["x", 2])],
      },
    );
  });

  it("a list of one is the term, not an and of one", () => {
    const only = ref("a");
    expect(visualNode("and", [only])).toBe(only);
    expect(visualNode("or", [])).toBeUndefined();
    expect(visualNode("or", [ref("a"), ref("b")])).toEqual({
      op: "or",
      args: [ref("a"), ref("b")],
    });
  });
});

describe("numbers (A.4)", () => {
  it("shows every digit and refuses what is not a finite number", () => {
    expect(numberText(0.1 + 0.2)).toBe("0.30000000000000004");
    expect(numberText(1e21)).toBe("1e+21");
    expect(parseNumber("0.30000000000000004")).toBe(0.30000000000000004);
    expect(parseNumber("  12 ")).toBe(12);
    expect(parseNumber("abc")).toBeNull();
    expect(parseNumber("Infinity")).toBeNull();
    expect(parseNumber("")).toBeNull();
  });
});
