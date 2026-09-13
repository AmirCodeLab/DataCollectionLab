/** Form IR §2.1: a question. */

import { useQuery } from "@tanstack/react-query";

import { paletteQuery } from "@/api/queries";
import { ExpressionEditor } from "@/builder/expressions/ExpressionEditor";
import {
  isExpr,
  type Expr,
  type FormIr,
  type QuestionNode,
} from "@/builder/ir";
import { QuestionTrace } from "@/builder/preview/QuestionTrace";
import { useBuilder } from "@/builder/store";
import { ChoicesEditor } from "./ChoicesEditor";
import { InterpolationArgs } from "./InterpolationArgs";
import {
  Checkbox,
  Field,
  I18nField,
  IdField,
  Select,
  TextField,
} from "./fields";

const SELECTS = new Set(["select_one", "select_multiple"]);

export function QuestionPanel({
  ir,
  node,
}: {
  ir: FormIr;
  node: QuestionNode;
}) {
  const setProperty = useBuilder((s) => s.setProperty);
  const select = useBuilder((s) => s.select);
  const palette = useQuery(paletteQuery());
  const set = (key: string, value: unknown) => setProperty(node.id, key, value);

  const types = palette.data?.types ?? [];
  const known = types.some((t) => t.dataType === node.dataType);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">
        Question <code className="font-normal text-slate-500">{node.id}</code>
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
      <Select
        label="type"
        value={node.dataType}
        onChange={(next) => set("dataType", next)}
      >
        {!known && (
          <option value={node.dataType}>
            {node.dataType} (not in the palette)
          </option>
        )}
        {types.map((type) => (
          <option
            key={type.dataType}
            value={type.dataType}
            disabled={type.status !== "collectable"}
          >
            {type.dataType}
            {type.status !== "collectable" && type.note
              ? ` — ${type.note}`
              : ""}
          </option>
        ))}
      </Select>
      <I18nField
        label="label"
        value={node.label}
        languages={ir.languages}
        onChange={(next) => set("label", next)}
        hint="{0}, {1} slots are filled from labelArgs, below (§7.1)"
      />
      <InterpolationArgs
        ir={ir}
        nodeId={node.id}
        argsKey="labelArgs"
        fills="label"
        value={node.labelArgs}
        onChange={(next) => set("labelArgs", next)}
      />
      <I18nField
        label="hint"
        value={node.hint}
        languages={ir.languages}
        onChange={(next) => set("hint", next)}
      />
      {SELECTS.has(node.dataType) && (
        <ChoicesEditor
          ir={ir}
          nodeId={node.id}
          value={node.choices}
          onChange={(next) => set("choices", next)}
        />
      )}
      <ExprOrBool
        label="required"
        value={node.required}
        onChange={(next) => set("required", next)}
        ir={ir}
        nodeId={node.id}
      />
      <ExprOrBool
        label="read-only"
        value={node.readOnly}
        onChange={(next) => set("readOnly", next)}
        ir={ir}
        nodeId={node.id}
      />
      <QuestionTrace ir={ir} node={node} />
      <ExpressionEditor
        label="relevant"
        value={node.relevant}
        onChange={(next) => set("relevant", next)}
        ir={ir}
        nodeId={node.id}
      />
      <ExpressionEditor
        label="constraint"
        value={node.constraint}
        onChange={(next) => set("constraint", next)}
        ir={ir}
        nodeId={node.id}
        selfPath={node.id}
      />
      <I18nField
        label="constraint message"
        value={node.constraintMessage}
        languages={ir.languages}
        onChange={(next) => set("constraintMessage", next)}
        hint="{0}, {1} slots are filled from constraintMessageArgs, below (§7.1)"
      />
      <InterpolationArgs
        ir={ir}
        nodeId={node.id}
        argsKey="constraintMessageArgs"
        fills="constraint message"
        value={node.constraintMessageArgs}
        onChange={(next) => set("constraintMessageArgs", next)}
      />
      <Select
        label="severity"
        value={node.severity ?? ""}
        onChange={(next) => set("severity", next === "" ? undefined : next)}
        hint="of the constraint: an error blocks finalisation, a warning does not (§6.1)"
      >
        <option value="">default (error)</option>
        <option value="error">error</option>
        <option value="warning">warning</option>
      </Select>
      <ExpressionEditor
        label="calculate"
        value={node.calculate}
        onChange={(next) => set("calculate", next)}
        ir={ir}
        nodeId={node.id}
      />
      <ExpressionEditor
        label="default"
        value={node.default}
        onChange={(next) => set("default", next)}
        ir={ir}
        nodeId={node.id}
      />
      <TextField
        label="appearance"
        value={node.appearance}
        onChange={(next) => set("appearance", next)}
        mono
      />
      <Checkbox
        label="sensitive"
        checked={node.sensitive === true}
        onChange={(on) => set("sensitive", on ? true : undefined)}
        hint="encrypted end-to-end in a field_level project. Anything that reads this value must be sensitive too — the publish check decides that, not this box (§10.2)."
      />
    </section>
  );
}

/** `required` and `readOnly` take an expression or a boolean (§2.1): off is
 *  the property absent, always is `true`, otherwise an expression. */
function ExprOrBool({
  label,
  value,
  onChange,
  ir,
  nodeId,
}: {
  label: string;
  value: Expr | boolean | undefined;
  onChange: (next: Expr | boolean | undefined) => void;
  ir: FormIr;
  nodeId: string;
}) {
  const mode =
    value === undefined || value === false
      ? "off"
      : value === true
        ? "always"
        : "expression";
  return (
    <Field label={label}>
      <select
        aria-label={`${label} mode`}
        value={mode}
        onChange={(e) => {
          const next = e.target.value;
          if (next === "off") onChange(undefined);
          else if (next === "always") onChange(true);
          else onChange(isExpr(value) ? value : { op: "lit", value: true });
        }}
        className="mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm"
      >
        <option value="off">no</option>
        <option value="always">always</option>
        <option value="expression">when an expression is true</option>
      </select>
      {mode === "expression" && (
        <div className="mt-1">
          <ExpressionEditor
            label={label}
            value={isExpr(value) ? value : undefined}
            onChange={(next) => onChange(next)}
            ir={ir}
            nodeId={nodeId}
          />
        </div>
      )}
    </Field>
  );
}
