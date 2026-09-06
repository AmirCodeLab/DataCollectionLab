/** Form IR §3: where a select's choices come from.
 *
 * The source list is the palette's `choiceSources`, served from the registry
 * like the types are; a source the registry marks `in_spec_only` is shown
 * disabled with the registry's own note. Inline items are edited as the IR
 * holds them — a list of `{value, label}` — and a dataset source is the four
 * fields §3 names, with the filter edited in row scope, where a bare name is
 * a column of the candidate row.
 */

import { useQuery } from "@tanstack/react-query";

import { paletteQuery } from "@/api/queries";
import { ExpressionEditor } from "@/builder/expressions/ExpressionEditor";
import type {
  ChoiceItem,
  ChoiceSource,
  DatasetChoices,
  FormIr,
  I18n,
  InlineChoices,
} from "@/builder/ir";
import { Field, I18nField, Select, TextField } from "./fields";

export function ChoicesEditor({
  ir,
  nodeId,
  value,
  onChange,
}: {
  ir: FormIr;
  nodeId: string;
  value: ChoiceSource | undefined;
  onChange: (next: ChoiceSource | undefined) => void;
}) {
  const palette = useQuery(paletteQuery());
  const sources = palette.data?.choiceSources ?? [];
  const kind = value?.kind ?? "";

  const switchTo = (next: string) => {
    if (next === "") onChange(undefined);
    else if (next === "inline") onChange({ kind: "inline", items: [] });
    else if (next === "dataset") {
      onChange({
        kind: "dataset",
        dataset: "",
        valueColumn: "",
        labelColumn: {},
      });
    }
  };

  return (
    <fieldset className="space-y-2 rounded border border-slate-200 p-2">
      <legend className="px-1 text-xs font-medium text-slate-600">
        choices
      </legend>
      <Select label="source" value={kind} onChange={switchTo}>
        <option value="">none yet</option>
        {sources.map((source) => (
          <option
            key={source.dataType}
            value={source.dataType}
            disabled={source.status !== "collectable"}
          >
            {source.dataType}
            {source.status !== "collectable" && source.note
              ? ` — ${source.note}`
              : ""}
          </option>
        ))}
      </Select>
      {sources.some((s) => s.status !== "collectable" && s.note) && (
        <ul className="text-[11px] text-slate-500">
          {sources
            .filter((s) => s.status !== "collectable" && s.note)
            .map((s) => (
              <li key={s.dataType}>
                <code>{s.dataType}</code>: {s.note}
              </li>
            ))}
        </ul>
      )}
      {value?.kind === "inline" && (
        <InlineItems ir={ir} value={value} onChange={onChange} />
      )}
      {value?.kind === "dataset" && (
        <DatasetSource
          ir={ir}
          nodeId={nodeId}
          value={value}
          onChange={onChange}
        />
      )}
    </fieldset>
  );
}

function InlineItems({
  ir,
  value,
  onChange,
}: {
  ir: FormIr;
  value: InlineChoices;
  onChange: (next: InlineChoices) => void;
}) {
  const items = value.items;
  const setItems = (next: ChoiceItem[]) => onChange({ ...value, items: next });
  const update = (index: number, patch: Partial<ChoiceItem>) =>
    setItems(
      items.map((item, i) => (i === index ? { ...item, ...patch } : item)),
    );
  const swap = (a: number, b: number) => {
    if (b < 0 || b >= items.length) return;
    const next = [...items];
    [next[a], next[b]] = [next[b], next[a]];
    setItems(next);
  };
  const languages = [
    ...new Set([
      ...ir.languages,
      ...items.flatMap((i) => Object.keys(i.label)),
    ]),
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-start text-slate-600">
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
                  aria-label={`choice ${String(index + 1)} value`}
                  value={item.value}
                  onChange={(e) => update(index, { value: e.target.value })}
                  className="w-full rounded border border-slate-300 px-1 py-0.5 font-mono"
                />
              </td>
              {languages.map((l) => (
                <td key={l}>
                  <input
                    aria-label={`choice ${String(index + 1)} label (${l})`}
                    value={item.label[l] ?? ""}
                    dir="auto"
                    onChange={(e) => {
                      const label: I18n = { ...item.label };
                      if (e.target.value === "") delete label[l];
                      else label[l] = e.target.value;
                      update(index, { label });
                    }}
                    className="w-full rounded border border-slate-300 px-1 py-0.5"
                  />
                </td>
              ))}
              <td className="whitespace-nowrap">
                <button
                  type="button"
                  aria-label={`choice ${String(index + 1)} up`}
                  onClick={() => swap(index, index - 1)}
                  className="px-1"
                >
                  ▲
                </button>
                <button
                  type="button"
                  aria-label={`choice ${String(index + 1)} down`}
                  onClick={() => swap(index, index + 1)}
                  className="px-1"
                >
                  ▼
                </button>
                <button
                  type="button"
                  aria-label={`remove choice ${String(index + 1)}`}
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
        onClick={() => setItems([...items, { value: "", label: {} }])}
        className="mt-1 rounded border px-2 py-0.5 text-xs"
      >
        add choice
      </button>
    </div>
  );
}

function DatasetSource({
  ir,
  nodeId,
  value,
  onChange,
}: {
  ir: FormIr;
  nodeId: string;
  value: DatasetChoices;
  onChange: (next: DatasetChoices) => void;
}) {
  return (
    <div className="space-y-2">
      <TextField
        label="dataset"
        value={value.dataset === "" ? undefined : value.dataset}
        onChange={(next) => onChange({ ...value, dataset: next ?? "" })}
        mono
      />
      <TextField
        label="value column"
        value={value.valueColumn === "" ? undefined : value.valueColumn}
        onChange={(next) => onChange({ ...value, valueColumn: next ?? "" })}
        mono
        hint="the cell value exactly — no trimming, no case folding (§3.1)"
      />
      <I18nField
        label="label column"
        value={
          Object.keys(value.labelColumn).length === 0
            ? undefined
            : value.labelColumn
        }
        languages={ir.languages}
        onChange={(next) => onChange({ ...value, labelColumn: next ?? {} })}
      />
      <Field
        label="filter"
        hint="evaluated per candidate row; a bare name is a column of that row (§3.2)"
      >
        <ExpressionEditor
          label="filter"
          value={value.filter}
          onChange={(next) => {
            if (next === undefined) {
              const { filter: _dropped, ...rest } = value;
              onChange(rest);
            } else {
              onChange({ ...value, filter: next });
            }
          }}
          ir={ir}
          nodeId={nodeId}
          rowScope
        />
      </Field>
    </div>
  );
}
