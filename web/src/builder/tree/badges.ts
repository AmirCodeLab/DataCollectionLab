/** What the tree says beside a node, read off the server's screen plan.
 *
 * Scope §3: the builder does not derive a screen plan, it asks for one and
 * renders it. So every badge here is a lookup into `CompileResponse.screens`
 * and `instancePlans` — which screen holds this question, how many others
 * are on it — and nothing is counted, numbered or inferred from the document.
 * When there is no answer for a node there is no badge, including the one
 * case the scope names ("never shown"): that check does not exist server-side
 * yet, and a console that guessed it would be the third implementation of
 * §11.1 the scope warns about.
 */

import type { CompileResponse, ScreenSummary } from "@/api/types";
import { isQuestion, isRepeat, type IrNode, type NodePath } from "@/builder/ir";

export type BadgeTone = "screen" | "computed" | "roster";

export interface Badge {
  text: string;
  tone: BadgeTone;
}

function inScreens(
  id: string,
  screens: ScreenSummary[] | undefined,
  prefix: string,
): Badge | null {
  const screen = screens?.find((s) => s.questionIds.includes(id));
  if (screen === undefined) return null;
  const others = screen.questionIds.length - 1;
  const text =
    others > 0
      ? `${prefix} ${String(screen.index)}, with ${String(others)} others`
      : `${prefix} ${String(screen.index)}`;
  return { text, tone: "screen" };
}

/** The badge for one node, or `null` when the plan says nothing about it. */
export function badgeFor(
  path: NodePath,
  result: CompileResponse | null,
): Badge | null {
  const node: IrNode = path.node;
  if (isRepeat(node)) {
    return { text: "roster — 1 screen, any number of rows", tone: "roster" };
  }
  if (!isQuestion(node) || result === null) return null;

  const found =
    path.repeat !== null
      ? inScreens(node.id, result.instancePlans?.[path.repeat.id], "row screen")
      : inScreens(node.id, result.screens, "screen");
  if (found !== null) return found;

  // §11.1: a calculate produces no screen. The plan leaves it out; the
  // absence is the fact and this is its name.
  if (node.calculate !== undefined) {
    return { text: "computed — never asked", tone: "computed" };
  }
  return null;
}
