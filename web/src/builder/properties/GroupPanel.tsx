/** Form IR §2.2: a group. It creates no data scope; `field-list` makes it
 *  one screen (§11.1). */

import { ExpressionEditor } from "@/builder/expressions/ExpressionEditor";
import type { FormIr, GroupNode } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { Checkbox, I18nField, IdField } from "./fields";

export function GroupPanel({ ir, node }: { ir: FormIr; node: GroupNode }) {
  const setProperty = useBuilder((s) => s.setProperty);
  const select = useBuilder((s) => s.select);
  const set = (key: string, value: unknown) => setProperty(node.id, key, value);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">
        Group <code className="font-normal text-slate-500">{node.id}</code>
      </h2>
      <IdField
        key={node.id}
        ir={ir}
        value={node.id}
        onChange={(next) => {
          set("id", next);
          select(next);
        }}
      />
      <I18nField
        label="label"
        value={node.label}
        languages={ir.languages}
        onChange={(next) => set("label", next)}
      />
      <Checkbox
        label="field-list: every question in this group on one screen"
        checked={node.appearance === "field-list"}
        onChange={(on) => set("appearance", on ? "field-list" : undefined)}
        hint="a nested plain group is flattened into it; a repeat cannot sit inside it (§11.1)"
      />
      <ExpressionEditor
        label="relevant"
        value={node.relevant}
        onChange={(next) => set("relevant", next)}
        ir={ir}
        nodeId={node.id}
      />
    </section>
  );
}
