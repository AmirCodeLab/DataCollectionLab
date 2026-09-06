/** The selected node's properties, or the form header.
 *
 * Every control here writes through the store, and the store writes through
 * `ir.ts`, so an edit to one node leaves every other node the object it was.
 * A node of a type this builder does not know is shown as it is and offered
 * nothing to change: the builder is an editor of a document it did not
 * necessarily write (scope §1), and the floor for such a node is the IR.
 */

import { find, isGroup, isQuestion, isRepeat } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { FormHeaderPanel } from "./FormHeaderPanel";
import { GroupPanel } from "./GroupPanel";
import { QuestionPanel } from "./QuestionPanel";
import { RepeatPanel } from "./RepeatPanel";

export function PropertiesPane() {
  const ir = useBuilder((s) => s.ir);
  const selectedId = useBuilder((s) => s.selectedId);

  if (ir === null) return null;
  if (selectedId === null) return <FormHeaderPanel ir={ir} />;

  const path = find(ir, selectedId);
  if (path === null) {
    return (
      <p className="text-sm text-slate-500">
        The selected node is no longer in the form.
      </p>
    );
  }
  const { node } = path;
  if (isQuestion(node)) return <QuestionPanel ir={ir} node={node} />;
  if (isGroup(node)) return <GroupPanel ir={ir} node={node} />;
  if (isRepeat(node)) return <RepeatPanel ir={ir} node={node} />;

  return (
    <section className="text-sm">
      <h2 className="font-semibold">
        <code>{node.id}</code>
      </h2>
      <p className="mt-1 text-slate-600">
        A node of type <code>{node.type}</code>, which this editor does not
        know. It is kept exactly as it is; change it as IR.
      </p>
      <pre className="mt-2 overflow-auto rounded bg-slate-50 p-2 text-xs">
        {JSON.stringify(node, null, 2)}
      </pre>
    </section>
  );
}
