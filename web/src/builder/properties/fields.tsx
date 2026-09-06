/** The small controls every panel is made of.
 *
 * One rule runs through them: an emptied property is **removed**, never left
 * as `""`. Absent and null are different things in the IR (§4.4 has a whole
 * section on null), and a label object with an empty string for a language
 * is a translation that exists and says nothing — not the same as a missing
 * one, which §7 falls back from. So every `onChange` here reports `undefined`
 * when there is nothing left, and the caller drops the key.
 */

import { useState, type ReactNode } from "react";

import type { FormIr, I18n } from "@/builder/ir";
import { idProblem } from "./ids";

export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <label className="block text-sm">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      {children}
      {hint !== undefined && (
        <span className="block text-[11px] text-slate-500">{hint}</span>
      )}
    </label>
  );
}

const INPUT = "mt-0.5 w-full rounded border border-slate-300 px-2 py-1 text-sm";

/** Free text; empty removes the property. */
export function TextField({
  label,
  value,
  onChange,
  mono = false,
  hint,
}: {
  label: string;
  value: string | undefined;
  onChange: (next: string | undefined) => void;
  mono?: boolean;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <input
        value={value ?? ""}
        onChange={(e) =>
          onChange(e.target.value === "" ? undefined : e.target.value)
        }
        className={`${INPUT} ${mono ? "font-mono" : ""}`}
      />
    </Field>
  );
}

/** A whole number; blank removes the property. */
export function NumberField({
  label,
  value,
  onChange,
  min,
}: {
  label: string;
  value: number | undefined;
  onChange: (next: number | undefined) => void;
  min?: number;
}) {
  return (
    <Field label={label}>
      <input
        type="number"
        min={min}
        value={value ?? ""}
        onChange={(e) => {
          const n = Number(e.target.value);
          onChange(
            e.target.value === "" || !Number.isFinite(n)
              ? undefined
              : Math.trunc(n),
          );
        }}
        className={INPUT}
      />
    </Field>
  );
}

/** One input per language. A language left blank is removed from the
 *  object; an object with nothing left is removed altogether. */
export function I18nField({
  label,
  value,
  languages,
  onChange,
  hint,
}: {
  label: string;
  value: I18n | undefined;
  languages: string[];
  onChange: (next: I18n | undefined) => void;
  hint?: string;
}) {
  const shown = new Set([...languages, ...Object.keys(value ?? {})]);
  const set = (language: string, text: string) => {
    const next: I18n = { ...(value ?? {}) };
    if (text === "") delete next[language];
    else next[language] = text;
    onChange(Object.keys(next).length === 0 ? undefined : next);
  };
  return (
    <fieldset className="text-sm">
      <legend className="text-xs font-medium text-slate-600">{label}</legend>
      {[...shown].map((language) => (
        <label key={language} className="mt-0.5 flex items-center gap-2">
          <code className="w-8 shrink-0 text-xs text-slate-500">
            {language}
          </code>
          <input
            aria-label={`${label} (${language})`}
            value={value?.[language] ?? ""}
            onChange={(e) => set(language, e.target.value)}
            dir="auto"
            className="w-full rounded border border-slate-300 px-2 py-1"
          />
        </label>
      ))}
      {hint !== undefined && (
        <p className="text-[11px] text-slate-500">{hint}</p>
      )}
    </fieldset>
  );
}

/** A §2.4 identifier, applied on blur and refused with a reason inline. */
export function IdField({
  ir,
  value,
  onChange,
}: {
  ir: FormIr;
  value: string;
  onChange: (next: string) => void;
}) {
  // Keyed by the id in every panel (`<IdField key={node.id} …/>`), so a
  // change applied elsewhere remounts it rather than syncing state in an
  // effect.
  const [draft, setDraft] = useState(value);
  const [problem, setProblem] = useState<string | null>(null);

  const commit = () => {
    if (draft === value) return;
    const reason = idProblem(ir, draft, value);
    setProblem(reason);
    if (reason === null) onChange(draft);
  };

  return (
    <Field
      label="id"
      hint="lower-case letters, digits and underscores; unique in the whole form (Form IR §2.4)"
    >
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === "Enter") commit();
        }}
        aria-invalid={problem !== null}
        className={`${INPUT} font-mono`}
      />
      {problem !== null && (
        <span className="block text-xs text-red-700">{problem}</span>
      )}
    </Field>
  );
}

export function Select({
  label,
  value,
  onChange,
  children,
  hint,
}: {
  label: string;
  value: string;
  onChange: (next: string) => void;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <Field label={label} hint={hint}>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={INPUT}
      >
        {children}
      </select>
    </Field>
  );
}

export function Checkbox({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (next: boolean) => void;
  hint?: string;
}) {
  return (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-1"
      />
      <span>
        {label}
        {hint !== undefined && (
          <span className="block text-[11px] text-slate-500">{hint}</span>
        )}
      </span>
    </label>
  );
}
