/** The selected node's properties, or the form header (scope §1, §2, §5).
 *
 * STUB — replaced in step 6.
 */

import { useBuilder } from "@/builder/store";

export function PropertiesPane() {
  const selectedId = useBuilder((s) => s.selectedId);
  return (
    <div className="text-sm text-slate-500">
      {selectedId === null ? "Form header." : `Selected: ${selectedId}`}
    </div>
  );
}
