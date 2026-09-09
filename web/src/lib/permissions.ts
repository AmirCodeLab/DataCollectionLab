/** A screen checks a permission by name from the contract, never a role
 *  (pilot scope §3.5): the first custom role would otherwise break the UI. */

import type { Me, Permission } from "@/api/types";

/** Whether `me` holds any one of `any`. */
export function may(me: Me, ...any: Permission[]): boolean {
  return any.some((permission) => me.permissions.includes(permission));
}

export type Section = "/submissions" | "/projects" | "/forms" | "/people" | "/roles";

/** The console's sections and what opens each: any one of the permissions. */
export const NAV: ReadonlyArray<{ to: Section; label: string; any: Permission[] }> = [
  { to: "/submissions", label: "Submissions", any: ["submission.view"] },
  {
    to: "/projects",
    label: "Projects",
    any: ["project.manage", "form.edit", "form.publish", "sample.upload", "team.manage"],
  },
  { to: "/forms", label: "Forms", any: ["form.edit", "form.publish", "submission.view"] },
  {
    to: "/people",
    label: "People",
    any: ["user.create", "user.approve", "user.deactivate", "user.assign_role", "team.manage"],
  },
  { to: "/roles", label: "Roles", any: ["user.assign_role"] },
];

/** The sections this person may open, in nav order. */
export function sectionsFor(me: Me) {
  return NAV.filter((item) => may(me, ...item.any));
}

/** Where a sign-in lands: the first section they may open, or null when the
 *  console has nothing for them — an enumerator, whose access is their
 *  handset's session, not a permission (pilot scope §3.5). */
export function homeFor(me: Me): Section | null {
  return sectionsFor(me)[0]?.to ?? null;
}
