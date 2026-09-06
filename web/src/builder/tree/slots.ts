/** Where a new node lands, relative to the selection. */

import { find, isContainer, type FormIr, type Slot } from "@/builder/ir";

/** After the selected node; at the end of a selected container; else at the
 *  end of the form. */
export function insertionSlot(ir: FormIr, selectedId: string | null): Slot {
  if (selectedId === null) return { parentId: null, index: ir.children.length };
  const path = find(ir, selectedId);
  if (path === null) return { parentId: null, index: ir.children.length };
  if (isContainer(path.node)) {
    return { parentId: path.node.id, index: path.node.children.length };
  }
  return { parentId: path.parent?.id ?? null, index: path.index + 1 };
}
