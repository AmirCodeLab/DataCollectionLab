/** A screen checks a permission by name from the contract, never a role
 *  (pilot scope §3.5): the first custom role would otherwise break the UI. */

import type { Me, Permission } from "@/api/types";

/** Whether `me` holds any one of `any`. */
export function may(me: Me, ...any: Permission[]): boolean {
  return any.some((permission) => me.permissions.includes(permission));
}
