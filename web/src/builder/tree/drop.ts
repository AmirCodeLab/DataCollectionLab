/** What a drop would do, decided before it lands. */

import { dropRefusal, type FormIr, type Slot } from "@/builder/ir";

/** A drop target as dnd-kit carries it: a slot in the document. */
export interface DropData {
  slot: Slot;
  /** What the row reads while hovered — "before X", "into Y". */
  label: string;
}

/** What dropping `activeId` on `target` would do: a move, or a refusal with
 *  the reason the tree shows. Pure, so the rule is testable without a drag. */
export function planDrop(
  ir: FormIr,
  activeId: string,
  target: DropData,
): { slot: Slot; refusal: string | null } {
  return {
    slot: target.slot,
    refusal: dropRefusal(ir, activeId, target.slot.parentId),
  };
}
