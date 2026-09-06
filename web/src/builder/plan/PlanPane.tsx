/** The screen plan the server returned: what an enumerator sees, where you
 *  check (scope §3). Never derived here.
 *
 * STUB — replaced in step 6.
 */

import { useBuilder } from "@/builder/store";

export function PlanPane() {
  const compile = useBuilder((s) => s.compile);
  return <div className="text-sm text-slate-500">Plan: {compile.status}</div>;
}
