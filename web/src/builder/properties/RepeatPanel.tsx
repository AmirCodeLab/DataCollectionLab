/** Form IR §2.3: a repeat, and the one choice that decides its rows.
 *
 * Scope §5: the four row sources are presented as ONE selector, not four
 * fields that happen to conflict. `countExpr` beside a `rowSource` is a
 * compile error, and a form that lets both be set and then reports the error
 * has taught the author nothing. Switching source removes the other source's
 * keys. The sample-backed source is shown disabled with the engine's own
 * conditions for refusing it, so the author reads which are outstanding
 * rather than "coming soon".
 */

import { ExpressionEditor } from "@/builder/expressions/ExpressionEditor";
import {
  fields,
  isRepeat,
  type FormIr,
  type I18n,
  type InlineRowSource,
  type RepeatNode,
  type RowItem,
} from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import {
  Checkbox,
  Field,
  I18nField,
  IdField,
  NumberField,
  Select,
} from "./fields";
import {
  DATASET_SOURCE_NOTE,
  rowSourceKind,
  withRowSource,
  type RowSourceKind,
} from "./rowSource";

export function RepeatPanel({ ir, node }: { ir: FormIr; node: RepeatNode }) {
  const setProperty = useBuilder((s) => s.setProperty);
  const editNode = useBuilder((s) => s.editNode);
  const select = useBuilder((s) => s.select);
  const set = (key: string, value: unknown) => setProperty(node.id, key, value);
  const kind = rowSourceKind(node);

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">
        Repeat <code className="font-normal text-slate-500">{node.id}</code>
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
      <ExpressionEditor
        label="relevant"
        value={node.relevant}
        onChange={(next) => set("relevant", next)}
        ir={ir}
        nodeId={node.id}
      />

      <Select
        label="where the rows come from"
        value={kind}
        onChange={(next) =>
          editNode(node.id, (n) =>
            isRepeat(n) ? withRowSource(n, next as RowSourceKind) : n,
          )
        }
        hint="one source; a repeat names exactly one (§2.3)"
      >
        <option value="enumerator">the enumerator adds rows</option>
        <option value="count">an answer decides the count</option>
        <option value="inline">a fixed list in the form</option>
        <option value="dataset" disabled={kind !== "dataset"}>
          rows from the sample (dataset) — {DATASET_SOURCE_NOTE}
        </option>
      </Select>
      {kind !== "dataset" && (
        <p className="text-[11px] text-slate-500">
          rows from the sample: {DATASET_SOURCE_NOTE}
        </p>
      )}

      {kind === "count" && (
        <ExpressionEditor
          label="count"
          value={node.countExpr}
          onChange={(next) => set("countExpr", next ?? { op: "lit", value: 1 })}
          ir={ir}
          nodeId={node.id}
        />
      )}
      {kind === "enumerator" && (
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label="minimum rows"
            value={node.minInstances}
            onChange={(next) => set("minInstances", next)}
            min={0}
          />
          <NumberField
            label="maximum rows"
            value={node.maxInstances}
            onChange={(next) => set("maxInstances", next)}
            min={0}
          />
        </div>
      )}
      {kind === "inline" && node.rowSource?.kind === "inline" && (
        <InlineRows
          ir={ir}
          node={node}
          value={node.rowSource}
          onChange={(next) => set("rowSource", next)}
          maxInstances={node.maxInstances}
          onMax={(next) => set("maxInstances", next)}
        />
      )}
      {kind === "dataset" && (
        <div className="rounded border border-amber-200 bg-amber-50 p-2 text-xs text-amber-900">
          <p>
            This repeat reads its rows from a dataset. {DATASET_SOURCE_NOTE}
          </p>
          <pre className="mt-1 overflow-auto text-[11px]">
            {JSON.stringify(node.rowSource, null, 2)}
          </pre>
        </div>
      )}

      <I18nField
        label="add-row label"
        value={node.addLabel}
        languages={ir.languages}
        onChange={(next) => set("addLabel", next)}
        hint="what the button reads; absent means the engine's default"
      />
      <I18nField
        label="row summary label"
        value={node.summaryLabel}
        languages={ir.languages}
        onChange={(next) => set("summaryLabel", next)}
        hint="tells one row from another in the roster; {0} slots need summaryLabelArgs, edited as IR (§2.3, §7.1)"
      />
    </section>
  );
}

function InlineRows({
  ir,
  node,
  value,
  onChange,
  maxInstances,
  onMax,
}: {
  ir: FormIr;
  node: RepeatNode;
  value: InlineRowSource;
  onChange: (next: InlineRowSource) => void;
  maxInstances: number | undefined;
  onMax: (next: number | undefined) => void;
}) {
  const items = value.items;
  const setItems = (next: RowItem[]) => onChange({ ...value, items: next });
  const update = (index: number, patch: Partial<RowItem>) =>
    setItems(
      items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  const languages = [
    ...new Set([
      ...ir.languages,
      ...items.flatMap((i) => Object.keys(i.label ?? {})),
    ]),
  ];
  // Only questions inside this repeat can be bound (§2.3), and an inline row
  // binds `value` and only `value`.
  const inside = fields(ir).filter((f) => f.repeatId === node.id);
  const bound = value.bind ?? {};
  const setBind = (questionId: string, on: boolean) => {
    const next = { ...bound };
    if (on) next[questionId] = "value";
    else delete next[questionId];
    const { bind: _dropped, ...rest } = value;
    onChange(Object.keys(next).length === 0 ? rest : { ...rest, bind: next });
  };

  return (
    <div className="space-y-2 rounded border border-slate-200 p-2">
      <p className="text-xs font-medium text-slate-600">rows</p>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-slate-600">
            <th className="text-start">value</th>
            {languages.map((l) => (
              <th key={l} className="text-start">
                label <code>{l}</code>
              </th>
            ))}
            <th />
          </tr>
        </thead>
        <tbody>
          {items.map((item, index) => (
            <tr key={index}>
              <td>
                <input
                  aria-label={`row ${String(index + 1)} value`}
                  value={item.value}
                  onChange={(e) => update(index, { value: e.target.value })}
                  className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono"
                />
              </td>
              {languages.map((l) => (
                <td key={l}>
                  <input
                    aria-label={`row ${String(index + 1)} label (${l})`}
                    value={item.label?.[l] ?? ""}
                    dir="auto"
                    onChange={(e) => {
                      const label: I18n = { ...(item.label ?? {}) };
                      if (e.target.value === "") delete label[l];
                      else label[l] = e.target.value;
                      const { label: _old, ...rest } = item;
                      const next: RowItem =
                        Object.keys(label).length === 0
                          ? rest
                          : { ...rest, label };
                      setItems(items.map((it, i) => (i === index ? next : it)));
                    }}
                    className="w-full rounded border border-slate-300 px-1 py-0.5"
                  />
                </td>
              ))}
              <td className="whitespace-nowrap">
                <button
                  type="button"
                  aria-label={`remove row ${String(index + 1)}`}
                  onClick={() => setItems(items.filter((_, i) => i !== index))}
                  className="px-1 text-red-700"
                >
                  ✕
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        type="button"
        onClick={() => setItems([...items, { value: "" }])}
        className="rounded border px-2 py-0.5 text-xs"
      >
        add row
      </button>
      <p className="text-[11px] text-slate-500">
        A row seeds the bound question with its <code>value</code>; a row the
        enumerator adds has no source row and starts empty (§2.3).
      </p>
      <Field
        label="bind rows to a question"
        hint="a question inside this repeat, seeded with the row's value"
      >
        {inside.length === 0 ? (
          <span className="block text-xs text-slate-500">
            no questions inside this repeat yet
          </span>
        ) : (
          <ul className="mt-0.5 space-y-0.5">
            {inside.map((f) => (
              <li key={f.id}>
                <Checkbox
                  label={`${f.label} (${f.id})`}
                  checked={bound[f.id] === "value"}
                  onChange={(on) => setBind(f.id, on)}
                />
              </li>
            ))}
          </ul>
        )}
      </Field>
      <div className="grid grid-cols-2 gap-2">
        <Checkbox
          label="enumerator may add rows"
          checked={value.allowAdd === true}
          onChange={(on) => {
            const { allowAdd: _a, ...rest } = value;
            onChange(on ? { ...rest, allowAdd: true } : rest);
          }}
        />
        <Checkbox
          label="enumerator may delete rows"
          checked={value.allowDelete === true}
          onChange={(on) => {
            const { allowDelete: _d, ...rest } = value;
            onChange(on ? { ...rest, allowDelete: true } : rest);
          }}
        />
      </div>
      {value.allowAdd === true && (
        <NumberField
          label="maximum rows"
          value={maxInstances}
          onChange={onMax}
          min={0}
        />
      )}
    </div>
  );
}
