/** The reference picker, as a disclosure and as a `<select>`. The grouping
 *  and the three decisions behind it live in `picker.ts`. */

import { useId, useState } from "react";

import type { FormIr } from "@/builder/ir";
import { pickerGroups, type PickerEntry } from "./picker";

export function SensitiveBadge() {
  return (
    <span className="ms-1 rounded bg-amber-100 px-1 text-[10px] font-medium uppercase tracking-wide text-amber-800">
      sensitive
    </span>
  );
}

export interface ReferencePickerProps {
  ir: FormIr;
  nodeId: string;
  onPick: (entry: PickerEntry) => void;
  /** Button text. */
  label?: string;
}

/** A disclosure listing every field; picking one calls back with its entry. */
export function ReferencePicker({
  ir,
  nodeId,
  onPick,
  label,
}: ReferencePickerProps) {
  const [filter, setFilter] = useState("");
  const [open, setOpen] = useState(false);
  const filterId = useId();
  const groups = pickerGroups(ir, nodeId);
  const needle = filter.trim().toLowerCase();
  const matches = (entry: PickerEntry): boolean =>
    needle === "" ||
    entry.path.toLowerCase().includes(needle) ||
    entry.label.toLowerCase().includes(needle);

  return (
    <div className="relative inline-block text-xs">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="rounded border border-slate-300 bg-white px-2 py-0.5 hover:bg-slate-50"
      >
        {label ?? "Insert field"} ▾
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Fields"
          className="absolute start-0 z-10 mt-1 max-h-72 w-80 overflow-auto rounded border border-slate-300 bg-white p-2 shadow"
        >
          <label htmlFor={filterId} className="sr-only">
            Filter fields
          </label>
          <input
            id={filterId}
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="filter…"
            className="mb-2 w-full rounded border border-slate-300 px-1 py-0.5"
          />
          {groups.map((g) => {
            const shown = g.entries.filter(matches);
            if (shown.length === 0) return null;
            return (
              <div key={g.title} className="mb-2">
                <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {g.title}
                </div>
                <ul>
                  {shown.map((entry) => (
                    <li key={entry.path}>
                      <button
                        type="button"
                        onClick={() => {
                          onPick(entry);
                          setOpen(false);
                        }}
                        className="flex w-full items-baseline gap-2 rounded px-1 py-0.5 text-start hover:bg-slate-100"
                      >
                        <code className="font-mono">{entry.path}</code>
                        <span className="truncate text-slate-600">
                          {entry.label}
                        </span>
                        {entry.sensitive && <SensitiveBadge />}
                        {entry.note !== null && (
                          <span className="ms-auto whitespace-nowrap text-slate-500">
                            {entry.note}
                          </span>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/** The same groups as a `<select>`, for a term's reference slot. The empty
 *  option is "not chosen yet"; a path that is not in the form (hand-written
 *  IR, `_metadata.*`) is kept as an extra option rather than dropped. */
export function ReferenceSelect({
  ir,
  nodeId,
  value,
  onChange,
  ariaLabel,
}: {
  ir: FormIr;
  nodeId: string;
  value: string;
  onChange: (path: string) => void;
  ariaLabel: string;
}) {
  const groups = pickerGroups(ir, nodeId);
  const known = groups.some((g) => g.entries.some((e) => e.path === value));
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="max-w-[14rem] rounded border border-slate-300 bg-white px-1 py-0.5 font-mono text-xs"
    >
      <option value="">choose a field…</option>
      {!known && value !== "" && <option value={value}>{value}</option>}
      {groups.map((g) => (
        <optgroup key={g.title} label={g.title}>
          {g.entries.map((entry) => (
            <option key={entry.path} value={entry.path}>
              {entry.path}
              {entry.sensitive ? " (sensitive)" : ""}
              {entry.note !== null ? ` — ${entry.note}` : ""}
            </option>
          ))}
        </optgroup>
      ))}
    </select>
  );
}
