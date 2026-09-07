/** The visual form builder: one draft, three panes.
 *
 * Tree on the start side (what the form is — where you edit), properties in
 * the middle, the server's screen plan on the end side (what an enumerator
 * sees — where you check). Scope §3 is the rule between them: selection is
 * shared, editing is not, and the plan is never derived here.
 *
 * The page owns the draft's lifecycle: open it (or start it from the latest
 * published version, or from nothing), save it on a pause in editing against
 * the revision it loaded, and stop on a conflict rather than merge.
 */

import { useEffect, useRef } from "react";
import { getRouteApi, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import {
  draftQuery,
  formListQuery,
  formVersionQuery,
  saveDraft,
} from "@/api/queries";
import type { FormSummary } from "@/api/types";
import { useAutoCompile } from "@/builder/compile";
import { IrMenu } from "@/builder/floor/IrMenu";
import { asFormIr, emptyForm } from "@/builder/ir";
import { PlanPane } from "@/builder/plan/PlanPane";
import { PropertiesPane } from "@/builder/properties/PropertiesPane";
import { PublishButton } from "@/builder/publish/PublishButton";
import { useBuilder } from "@/builder/store";
import { TreePane } from "@/builder/tree/TreePane";

const route = getRouteApi("/forms/$formId");

/** How long after the last edit a save goes out. */
export const SAVE_DEBOUNCE_MS = 1_500;

export function BuilderPage() {
  const { formId } = route.useParams();
  const forms = useQuery(formListQuery());
  const form = forms.data?.forms.find((f) => f.id === formId) ?? null;

  if (forms.isPending) return <p className="text-slate-500">Loading…</p>;
  if (forms.isError) {
    return (
      <p className="text-red-600">
        Could not load forms: {String(forms.error)}
      </p>
    );
  }
  if (form === null) {
    return (
      <p className="text-red-600">
        No form with id <code>{formId}</code>.{" "}
        <Link to="/forms" className="text-blue-700 hover:underline">
          Back to forms
        </Link>
      </p>
    );
  }
  return <Opener form={form} />;
}

/** Load the draft, or the document a new draft starts from, into the store. */
function Opener({ form }: { form: FormSummary }) {
  const draft = useQuery(draftQuery(form.id));
  const startFrom = form.latestVersionId ?? null;
  const version = useQuery({
    ...formVersionQuery(startFrom ?? ""),
    enabled: draft.data === null && startFrom !== null,
  });
  const open = useBuilder((s) => s.open);
  const close = useBuilder((s) => s.close);
  const opened = useBuilder((s) => s.formId);

  useEffect(() => close, [close]);

  useEffect(() => {
    if (opened === form.id || draft.data === undefined) return;
    if (draft.data !== null) {
      const parsed = asFormIr(draft.data.ir);
      if ("ir" in parsed) open(form.id, parsed.ir, draft.data.revision);
      return;
    }
    if (startFrom === null) {
      open(form.id, emptyForm(form.formId, form.title), null);
      return;
    }
    if (version.data === undefined) return;
    const parsed = asFormIr(version.data.form);
    if ("ir" in parsed) open(form.id, parsed.ir, null);
  }, [opened, form, draft.data, version.data, startFrom, open]);

  if (
    draft.isPending ||
    (draft.data === null && startFrom !== null && version.isPending)
  ) {
    return <p className="text-slate-500">Loading the draft…</p>;
  }
  if (draft.isError) {
    return (
      <p className="text-red-600">
        Could not load the draft: {String(draft.error)}
      </p>
    );
  }
  if (version.isError) {
    return (
      <p className="text-red-600">
        Could not load the published version to start from:{" "}
        {String(version.error)}
      </p>
    );
  }
  const source = draft.data !== null ? draft.data.ir : version.data?.form;
  const parsed = source === undefined ? null : asFormIr(source);
  if (parsed !== null && "reason" in parsed) {
    return (
      <section>
        <h1 className="text-xl font-semibold">{form.title}</h1>
        <p className="mt-2 text-amber-700">
          This document cannot be opened in the editor: {parsed.reason}. It has
          not been changed. Download it, fix it, and upload it back.
        </p>
        <pre className="mt-4 max-h-[60vh] overflow-auto rounded bg-slate-50 p-3 text-xs">
          {JSON.stringify(source, null, 2)}
        </pre>
      </section>
    );
  }
  if (opened !== form.id) return <p className="text-slate-500">Opening…</p>;
  return <Editor form={form} />;
}

function Editor({ form }: { form: FormSummary }) {
  useAutoSave(form.id);
  useAutoCompile();
  const title = useBuilder(
    (s) => s.ir?.title[s.ir.defaultLanguage] ?? form.title,
  );

  return (
    <section className="flex h-[calc(100vh-7rem)] flex-col">
      <header className="flex flex-wrap items-center gap-3 border-b border-slate-200 pb-2">
        <Link to="/forms" className="text-sm text-blue-700 hover:underline">
          Forms
        </Link>
        <h1 className="text-lg font-semibold">{title}</h1>
        <code className="text-xs text-slate-500">{form.formId}</code>
        <SaveStatus />
        <span className="ms-auto flex items-center gap-3">
          <IrMenu />
          <PublishButton
            projectId={form.projectId}
            publishedVersions={form.versions}
          />
        </span>
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[18rem_minmax(0,1fr)_22rem] gap-4 pt-3">
        <aside className="min-h-0 overflow-auto border-e border-slate-200 pe-3">
          <TreePane />
        </aside>
        <div className="min-h-0 overflow-auto">
          <PropertiesPane />
        </div>
        <aside className="min-h-0 overflow-auto border-s border-slate-200 ps-3">
          <PlanPane />
        </aside>
      </div>
    </section>
  );
}

function SaveStatus() {
  const save = useBuilder((s) => s.save);
  const revision = useBuilder((s) => s.revision);
  const label: Record<typeof save.status, string> = {
    clean:
      revision === null
        ? "not saved yet"
        : `saved (revision ${String(revision)})`,
    dirty: "unsaved changes",
    saving: "saving…",
    conflict: "conflict",
    failed: "save failed",
  };
  const tone =
    save.status === "conflict" || save.status === "failed"
      ? "text-red-700"
      : save.status === "clean"
        ? "text-slate-500"
        : "text-amber-700";
  return (
    <span className={`text-xs ${tone}`} role="status" aria-label="save status">
      {label[save.status]}
      {save.message !== null && <span className="ms-2">— {save.message}</span>}
      {save.status === "conflict" && (
        <span className="ms-2">
          Someone else saved this draft. Reload to take their copy; your changes
          here are not merged.
        </span>
      )}
    </span>
  );
}

/** Save on a pause in editing, against the revision this page loaded.
 *
 * One request at a time. An edit made while a save is in flight leaves the
 * document dirty when the answer lands (`saveSucceeded` compares by
 * identity), which re-runs this effect and schedules the next save.
 */
function useAutoSave(formId: string) {
  const ir = useBuilder((s) => s.ir);
  const saved = useBuilder((s) => s.saved);
  const status = useBuilder((s) => s.save.status);
  const inFlight = useRef(false);

  useEffect(() => {
    if (ir === null || ir === saved) return;
    if (status === "conflict" || status === "saving" || inFlight.current)
      return;
    const handle = setTimeout(() => {
      const current = useBuilder.getState();
      if (current.ir === null || current.ir === current.saved) return;
      const sent = current.ir;
      inFlight.current = true;
      current.saveStarted();
      // Omitted, not null, for a draft that does not exist yet: the schema
      // reads an absent revision as "I am starting this draft".
      const request =
        current.revision === null
          ? { ir: sent }
          : { ir: sent, expectedRevision: current.revision };
      saveDraft(formId, request)
        .then((doc) => {
          useBuilder.getState().saveSucceeded(sent, doc.revision);
        })
        .catch((error: unknown) => {
          const message =
            error instanceof Error ? error.message : String(error);
          if (error instanceof ApiError && error.status === 409) {
            useBuilder.getState().saveConflicted(message);
          } else {
            useBuilder.getState().saveFailed(message);
          }
        })
        .finally(() => {
          inFlight.current = false;
        });
    }, SAVE_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [formId, ir, saved, status]);
}
