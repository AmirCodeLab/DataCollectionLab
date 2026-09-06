/** Form IR §2.4: what an identifier is, and that it is unique in the whole
 *  form, repeats included. */

import { ID_PATTERN, allIds, type FormIr } from "@/builder/ir";

export function idProblem(
  ir: FormIr,
  candidate: string,
  current: string,
): string | null {
  if (!ID_PATTERN.test(candidate)) {
    return `"${candidate}" is not an identifier: lower-case letters, digits and underscores, starting with a letter`;
  }
  if (candidate !== current && allIds(ir).has(candidate)) {
    return `"${candidate}" is already used in this form — ids are unique across the whole form, repeats included`;
  }
  return null;
}
