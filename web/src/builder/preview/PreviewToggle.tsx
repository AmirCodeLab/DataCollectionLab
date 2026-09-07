/** Opens and closes the preview pane. */

import { usePreviewOpen } from "./previewStore";

export function PreviewToggle() {
  const open = usePreviewOpen((s) => s.open);
  const toggle = usePreviewOpen((s) => s.toggle);
  return (
    <button
      type="button"
      aria-pressed={open}
      className="rounded border border-slate-300 px-3 py-1 text-sm hover:bg-slate-50 aria-pressed:bg-slate-900 aria-pressed:text-white"
      onClick={toggle}
    >
      Preview
    </button>
  );
}
