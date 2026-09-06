/** The groups a reference picker shows, by where the author is (scope §2,
 *  "The reference picker").
 *
 * Three decisions, and this file is where they are kept:
 *
 * 1. Everything is shown and nothing is scoped. §4.2 puts every field within
 *    reach of every expression — outer fields by name, an instance's by
 *    position, all instances through an aggregate — so a picker that hid one
 *    would be inventing a rule the engine does not have.
 * 2. From inside a repeat, this instance's fields come first, unprefixed. From
 *    outside, an instance's field is `members[0].name` with the index spelled
 *    out — "first instance" — because a bare `[0]` is easy to read as "any
 *    member". The aggregate form `members[].income` is offered beside it.
 * 3. A sensitive field is shown with a badge, never hidden and never refused.
 *    `check_publishable` decides what may be written; the badge is so the
 *    author learns at pick time rather than at publish time.
 */

import { fields, find, type FormIr } from "@/builder/ir";

export interface PickerEntry {
  /** What goes inside `${...}`. */
  path: string;
  id: string;
  label: string;
  dataType: string;
  sensitive: boolean;
  /** "first instance" / "every instance …" — what the index form means. */
  note: string | null;
  /** Valid only as an aggregate's argument (§4.2). */
  aggregateOnly: boolean;
}

export interface PickerGroup {
  title: string;
  entries: PickerEntry[];
}

export const FIRST_INSTANCE = "first instance";
export const EVERY_INSTANCE =
  "every instance (inside count, sum, min, max only)";

/** The groups, in the order the picker shows them. */
export function pickerGroups(ir: FormIr, nodeId: string): PickerGroup[] {
  const here = find(ir, nodeId);
  const currentRepeat = here?.repeat?.id ?? null;
  const all = fields(ir);

  const groups: PickerGroup[] = [];
  const byTitle = new Map<string, PickerGroup>();
  const group = (title: string): PickerGroup => {
    let found = byTitle.get(title);
    if (found === undefined) {
      found = { title, entries: [] };
      byTitle.set(title, found);
      groups.push(found);
    }
    return found;
  };

  if (currentRepeat !== null) {
    const mine = group(`This instance — ${currentRepeat}`);
    for (const field of all) {
      if (field.repeatId !== currentRepeat) continue;
      mine.entries.push({
        path: field.id,
        id: field.id,
        label: field.label,
        dataType: field.dataType,
        sensitive: field.sensitive,
        note: null,
        aggregateOnly: false,
      });
    }
  }

  for (const field of all) {
    if (field.repeatId !== null && field.repeatId === currentRepeat) continue;
    const title =
      field.containers.length === 0 ? "Form" : field.containers.join(" › ");
    const target = group(title);
    if (field.repeatId === null) {
      target.entries.push({
        path: field.id,
        id: field.id,
        label: field.label,
        dataType: field.dataType,
        sensitive: field.sensitive,
        note: null,
        aggregateOnly: false,
      });
      continue;
    }
    // A field in a repeat the author is not inside: the instance form and
    // the aggregate form, both shown as what they are.
    target.entries.push({
      path: `${field.repeatId}[0].${field.id}`,
      id: field.id,
      label: field.label,
      dataType: field.dataType,
      sensitive: field.sensitive,
      note: FIRST_INSTANCE,
      aggregateOnly: false,
    });
    target.entries.push({
      path: `${field.repeatId}[].${field.id}`,
      id: field.id,
      label: field.label,
      dataType: field.dataType,
      sensitive: field.sensitive,
      note: EVERY_INSTANCE,
      aggregateOnly: true,
    });
  }
  return groups;
}
