/** Every form, and where a new one starts.
 *
 * A form here is a row, not a version: one the builder started has no
 * versions and a draft, one that was imported has versions and maybe a draft
 * too. The list says which is which because the two look identical otherwise.
 */

import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createForm, formListQuery, projectListQuery } from "@/api/queries";
import type { FormSummary } from "@/api/types";
import { ID_PATTERN } from "@/builder/ir";
import { Td, Th } from "@/components/Table";

export function FormsPage() {
  const forms = useQuery(formListQuery());

  return (
    <section>
      <h1 className="text-xl font-semibold">Forms</h1>
      <p className="mt-1 text-sm text-slate-600">
        A form is edited as a draft and published as a numbered version. The
        draft is never the version: publishing runs every check the import path
        runs, and nothing else makes a version.
      </p>

      <NewForm />

      {forms.isPending && <p className="mt-4 text-slate-500">Loading…</p>}
      {forms.isError && (
        <p className="mt-4 text-red-600">
          Could not load forms: {String(forms.error)}
        </p>
      )}

      {forms.data && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[44rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-slate-600">
                <Th>Title</Th>
                <Th>Form id</Th>
                <Th>Published versions</Th>
                <Th>Draft</Th>
                <Th>Edit</Th>
              </tr>
            </thead>
            <tbody>
              {forms.data.forms.map((form) => (
                <FormRow key={form.id} form={form} />
              ))}
            </tbody>
          </table>
          {forms.data.forms.length === 0 && (
            <p className="py-6 text-slate-500">No forms yet.</p>
          )}
        </div>
      )}
    </section>
  );
}

function FormRow({ form }: { form: FormSummary }) {
  const published =
    form.versions.length === 0 ? "none" : form.versions.join(", ");
  return (
    <tr className="border-b border-slate-100">
      <Td>{form.title}</Td>
      <Td>
        <code>{form.formId}</code>
      </Td>
      <Td>{published}</Td>
      <Td>
        {form.hasDraft ? (
          <span className="text-amber-700">unpublished changes</span>
        ) : (
          <span className="text-slate-500">none</span>
        )}
      </Td>
      <Td>
        <Link
          to="/forms/$formId"
          params={{ formId: form.id }}
          className="text-blue-700 hover:underline"
        >
          {form.hasDraft
            ? "Open draft"
            : form.versions.length === 0
              ? "Start"
              : "Start a draft from the latest version"}
        </Link>
      </Td>
    </tr>
  );
}

function NewForm() {
  const projects = useQuery(projectListQuery());
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [projectId, setProjectId] = useState("");
  const [formId, setFormId] = useState("");
  const [title, setTitle] = useState("");

  const create = useMutation({
    mutationFn: createForm,
    onSuccess: async (form) => {
      await queryClient.invalidateQueries({ queryKey: ["forms"] });
      await navigate({ to: "/forms/$formId", params: { formId: form.id } });
    },
  });

  const idOk = ID_PATTERN.test(formId);
  const ready = projectId !== "" && idOk && title.trim() !== "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!ready) return;
    create.mutate({ projectId, formId, title: title.trim() });
  };

  return (
    <form
      onSubmit={submit}
      className="mt-4 flex flex-wrap items-end gap-3 rounded border border-slate-200 p-3"
    >
      <label className="text-sm">
        <span className="block text-xs text-slate-600">Project</span>
        <select
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          className="mt-1 rounded border border-slate-300 px-2 py-1"
        >
          <option value="">choose…</option>
          {projects.data?.projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="text-sm">
        <span className="block text-xs text-slate-600">Form id</span>
        <input
          value={formId}
          onChange={(e) => setFormId(e.target.value)}
          placeholder="household_survey"
          className="mt-1 rounded border border-slate-300 px-2 py-1 font-mono"
          aria-invalid={formId !== "" && !idOk}
        />
      </label>
      <label className="text-sm">
        <span className="block text-xs text-slate-600">Title</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 rounded border border-slate-300 px-2 py-1"
        />
      </label>
      <button
        type="submit"
        disabled={!ready || create.isPending}
        className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white disabled:opacity-50"
      >
        New form
      </button>
      {formId !== "" && !idOk && (
        <span className="text-xs text-amber-700">
          a form id is lower-case letters, digits and underscores, starting with
          a letter (Form IR §1)
        </span>
      )}
      {create.isError && (
        <span className="text-xs text-red-600">{String(create.error)}</span>
      )}
    </form>
  );
}
