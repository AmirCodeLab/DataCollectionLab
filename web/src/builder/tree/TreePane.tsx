/** The form as a tree: what the form is, where you edit (scope §3).
 *
 * STUB — replaced in step 6.
 */

import { useBuilder } from "@/builder/store";

export function TreePane() {
  const ir = useBuilder((s) => s.ir);
  return (
    <div className="text-sm text-slate-500">
      {ir === null ? "No form." : `${ir.children.length} top-level nodes.`}
    </div>
  );
}
