/** Whether the preview pane is open. Its own store, not the builder's: the
 *  builder store holds the document and the server's answers about it, and
 *  which pane is showing is neither. (A store shares no file with a component,
 *  so it hot-reloads — see lib/autoRefresh.ts.) */

import { create } from "zustand";

interface PreviewOpenState {
  open: boolean;
  setOpen: (open: boolean) => void;
  toggle: () => void;
}

export const usePreviewOpen = create<PreviewOpenState>((set) => ({
  open: false,
  setOpen: (open) => set({ open }),
  toggle: () => set((s) => ({ open: !s.open })),
}));
