/** Where a new node comes from: the palette the server serves.
 *
 * Scope §1: the type palette is served, not copied. `GET /forms/palette` is
 * the registry (`specs/collectable-types-v0.1.json`) over the wire, and the
 * day a type ships this menu gains it with no console change. A type the
 * registry marks `in_spec_only` is shown disabled with the registry's own
 * sentence, so the author reads why rather than wondering where it went.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { paletteQuery } from "@/api/queries";
import {
  newGroup,
  newQuestion,
  newRepeat,
  uniqueId,
  type IrNode,
} from "@/builder/ir";
import { insertionSlot } from "./slots";
import { useBuilder } from "@/builder/store";

export function AddMenu() {
  const [open, setOpen] = useState(false);
  const palette = useQuery(paletteQuery());
  const ir = useBuilder((s) => s.ir);
  const selectedId = useBuilder((s) => s.selectedId);
  const insert = useBuilder((s) => s.insert);

  if (ir === null) return null;

  const add = (make: (id: string) => IrNode, base: string) => {
    insert(insertionSlot(ir, selectedId), make(uniqueId(ir, base)));
    setOpen(false);
  };
  const language = ir.defaultLanguage;

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="rounded border border-slate-300 px-2 py-0.5 text-xs hover:bg-slate-50"
      >
        Add…
      </button>
      {open && (
        <div
          role="menu"
          className="absolute start-0 z-10 mt-1 w-72 rounded border border-slate-200 bg-white p-2 text-xs shadow"
        >
          <p className="mb-1 font-medium text-slate-600">Question</p>
          {palette.isPending && (
            <p className="text-slate-500">Loading the palette…</p>
          )}
          {palette.isError && (
            <p className="text-red-600">
              Could not load the palette: {String(palette.error)}
            </p>
          )}
          {palette.data && (
            <ul className="max-h-64 overflow-auto">
              {palette.data.types.map((type) => {
                const enabled = type.status === "collectable";
                return (
                  <li key={type.dataType}>
                    <button
                      type="button"
                      role="menuitem"
                      disabled={!enabled}
                      onClick={() =>
                        add(
                          (id) => newQuestion(id, type.dataType, language),
                          type.dataType,
                        )
                      }
                      className="flex w-full flex-col items-start rounded px-1 py-0.5 text-start hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
                    >
                      <code>{type.dataType}</code>
                      {!enabled && type.note && (
                        <span className="text-[11px] text-slate-500">
                          {type.note}
                        </span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="mb-1 mt-2 font-medium text-slate-600">Structure</p>
          <button
            type="button"
            role="menuitem"
            onClick={() => add((id) => newGroup(id, language), "group")}
            className="block w-full rounded px-1 py-0.5 text-start hover:bg-slate-50"
          >
            Group
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() =>
              add(
                (id) => ({
                  ...newGroup(id, language),
                  appearance: "field-list",
                }),
                "page",
              )
            }
            className="block w-full rounded px-1 py-0.5 text-start hover:bg-slate-50"
          >
            Group (field-list — one screen)
          </button>
          <button
            type="button"
            role="menuitem"
            onClick={() => add((id) => newRepeat(id, language), "repeat")}
            className="block w-full rounded px-1 py-0.5 text-start hover:bg-slate-50"
          >
            Repeat
          </button>
        </div>
      )}
    </div>
  );
}
