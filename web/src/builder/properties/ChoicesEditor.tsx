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
  RowsChoices,
} from "@/builder/ir";
import { find, repeats } from "@/builder/ir";
import { Checkbox, Field, I18nField, Select, TextField } from "./fields";

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
  const rosters = repeats(ir);
  // The repeat this question sits in, if any. It is the default for a rows
  // list because it is the case the feature exists for — MICS6 HL14 asks for
  // the mother's line number ON the member's own row — and because it is the
  // only placement where `excludeSelf` means anything (§10.2).
  const here = find(ir, nodeId)?.repeat?.id ?? null;

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
    } else if (next === "rows") {
      onChange({ kind: "rows", repeat: here ?? rosters[0]?.id ?? "" });
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
      {value?.kind === "rows" && (
        <RowsSource
          ir={ir}
          nodeId={nodeId}
          here={here}
          rosters={rosters}
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

/** Form IR §3.3: a repeat picker where the dataset kind has a key picker.
 *
 * Three controls and one rule. The repeat decides whose rows are offered; the
 * answer stores the **instance id**, which is why there is nothing to pick a
 * value column from. `excludeSelf` is offered only where it is legal — inside
 * the repeat the list comes from — because outside it there is no instance to
 * exclude and §10.2 refuses the document; showing the checkbox anyway would
 * let an author build a form the publish gate rejects for a reason the screen
 * never mentioned.
 */
function RowsSource({
  ir,
  nodeId,
  here,
  rosters,
  value,
  onChange,
}: {
  ir: FormIr;
  nodeId: string;
  here: string | null;
  rosters: { id: string; label: string }[];
  value: RowsChoices;
  onChange: (next: RowsChoices) => void;
}) {
  const inside = here !== null && here === value.repeat;
  const summarised = (repeatId: string): boolean => {
    const node = find(ir, repeatId)?.node;
    const label = (node as { summaryLabel?: I18n } | undefined)?.summaryLabel;
    return label !== undefined && Object.keys(label).length > 0;
  };

  return (
    <div className="space-y-2">
      <Select
        label="rows of"
        value={value.repeat}
        onChange={(next) => {
          // Dropping a now-illegal excludeSelf rather than carrying it: the
          // author changed which roster is offered, and the flag would be a
          // §10.2 refusal at publish with nothing on this screen to explain it.
          const next_inside = here !== null && here === next;
          const { excludeSelf: _dropped, ...rest } = value;
          onChange(
            next_inside && value.excludeSelf === true
              ? { ...rest, repeat: next, excludeSelf: true }
              : { ...rest, repeat: next },
          );
        }}
        hint="the answer stores the row's identity, so it still means the same person after another row is deleted (§3.3)"
      >
        {rosters.length === 0 && <option value="">this form has no repeat</option>}
        {rosters.map((roster) => (
          <option key={roster.id} value={roster.id}>
            {roster.id} — {roster.label}
          </option>
        ))}
      </Select>
      {value.repeat !== "" && !summarised(value.repeat) && (
        <p className="text-[11px] text-amber-700">
          <code>{value.repeat}</code> has no summary label, so this question
          will offer position numbers — 1, 2, 3 — rather than names (§10.3).
          Set one on the repeat.
        </p>
      )}
      {inside ? (
        <Checkbox
          label="not the person on this row"
          checked={value.excludeSelf === true}
          onChange={(next) => {
            if (next) onChange({ ...value, excludeSelf: true });
            else {
              const { excludeSelf: _dropped, ...rest } = value;
              onChange(rest);
            }
          }}
          hint="MICS6 HL14: nobody is their own mother, and the paper form has no list to offer them from"
        />
      ) : (
        <p className="text-[11px] text-slate-500">
          “Not the person on this row” is offered only on a question inside the
          repeat it lists, because outside one there is no row to exclude
          (§10.2).
        </p>
      )}
      <Field
        label="filter"
        hint="evaluated per candidate row; $row.field is that member's answer, a bare name is this row's (§3.3)"
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
