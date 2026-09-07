/** Form IR §1: the document header. */

import { useState } from "react";

import type { FormIr } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { Field, I18nField, Select } from "./fields";

export function FormHeaderPanel({ ir }: { ir: FormIr }) {
  const editForm = useBuilder((s) => s.editForm);
  const [newLanguage, setNewLanguage] = useState("");

  const addLanguage = () => {
    const code = newLanguage.trim();
    if (code === "" || ir.languages.includes(code)) return;
    editForm({ languages: [...ir.languages, code] });
    setNewLanguage("");
  };
  const removeLanguage = (code: string) => {
    if (code === ir.defaultLanguage) return;
    editForm({ languages: ir.languages.filter((l) => l !== code) });
  };

  return (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">Form</h2>
      <Field
        label="form id"
        hint="fixed when the form was created; it is the key every submission carries"
      >
        <code className="block">{ir.formId}</code>
      </Field>
      <Field label="version">
        <span className="block text-sm">{String(ir.version)}</span>
      </Field>
      <I18nField
        label="title"
        value={ir.title}
        languages={ir.languages}
        onChange={(next) => editForm({ title: next ?? {} })}
      />
      <fieldset className="text-sm">
        <legend className="text-xs font-medium text-slate-600">
          languages
        </legend>
        <ul className="mt-0.5 flex flex-wrap gap-1">
          {ir.languages.map((code) => (
            <li
              key={code}
              className="flex items-center gap-1 rounded border border-slate-300 px-1.5 py-0.5"
            >
              <code>{code}</code>
              {code !== ir.defaultLanguage && (
                <button
                  type="button"
                  aria-label={`remove language ${code}`}
                  onClick={() => removeLanguage(code)}
                  className="text-slate-500 hover:text-red-700"
                >
                  ✕
                </button>
              )}
            </li>
          ))}
        </ul>
        <div className="mt-1 flex gap-1">
          <input
            aria-label="new language code"
            value={newLanguage}
            onChange={(e) => setNewLanguage(e.target.value)}
            placeholder="ar"
            className="w-24 rounded border border-slate-300 px-2 py-1 font-mono"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addLanguage();
              }
            }}
          />
          <button
            type="button"
            onClick={addLanguage}
            className="rounded border px-2 text-xs"
          >
            add language
          </button>
        </div>
      </fieldset>
      <Select
        label="default language"
        value={ir.defaultLanguage}
        onChange={(next) => editForm({ defaultLanguage: next })}
        hint="must be one of the languages; a missing translation falls back to it (Form IR §7)"
      >
        {ir.languages.map((code) => (
          <option key={code} value={code}>
            {code}
          </option>
        ))}
      </Select>
    </section>
  );
}
