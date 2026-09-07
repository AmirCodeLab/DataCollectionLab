/** Close a popover the way people expect to close one.
 *
 * Escape closes it. A pointer going down anywhere outside it closes it. The
 * first end-to-end run found the Insert-field picker ignoring both, so a
 * click into the code field left it open and the typing landed in the
 * picker's filter box — a wrong answer that looked like the right one.
 */

import { useEffect, type RefObject } from "react";

export function useDismiss(
  open: boolean,
  container: RefObject<HTMLElement | null>,
  close: () => void,
): void {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
    };
    const onPointer = (event: PointerEvent) => {
      const target = event.target;
      if (target instanceof Node && container.current?.contains(target)) return;
      close();
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [open, container, close]);
}
