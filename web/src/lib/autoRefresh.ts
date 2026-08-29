/** Whether the auto-refreshing views poll.
 *
 * Sticky across navigation: switching to a submission should not silently turn
 * polling back on for someone who deliberately turned it off.
 *
 * In its own module rather than beside `RefreshControls` because a file that
 * exports both a component and a store cannot be hot-reloaded — every edit to
 * the control would reset this back to `true`, which is the state the person
 * at the keyboard just turned off.
 */

import { create } from "zustand";

export const useAutoRefresh = create<{
  enabled: boolean;
  setEnabled: (enabled: boolean) => void;
}>((set) => ({
  enabled: true,
  setEnabled: (enabled) => set({ enabled }),
}));
