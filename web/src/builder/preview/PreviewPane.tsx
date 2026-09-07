/** What this form looks like to an enumerator — the engine's answer, drawn.
 *
 * Scope §4: preview is inspection. An author opens it, walks the form and
 * closes it. The engine that runs it is the one the handset runs, compiled to
 * Wasm, and this pane holds no state of its own about the form: every
 * question, value, relevance, count, row and blocker below is read out of the
 * `PreviewState` the engine returned for the last operation. A preview that
 * computed any of those itself would be a third engine, reachable by no
 * vector (docs/project-conventions.md, the conformance boundary).
 *
 * The bar at the bottom is the handset's: Previous, "N / M", Next or
 * Finalize. §11.2's pair, and it does not move inside a row (§11.3).
 */

import clsx from "clsx";

import type {
  EngineValue,
  PreviewQuestion,
  PreviewRoster,
  PreviewState,
} from "@/builder/engine/facade";
import { todayIso, usePreviewSession } from "@/builder/engine/session";
import { useBuilder } from "@/builder/store";

export function PreviewPane() {
  const ir = useBuilder((s) => s.ir);
  const preview = usePreviewSession(ir, todayIso());

  if (preview.status === "unavailable") {
    return (
      <section aria-label="preview" className="text-sm">
        <h2 className="font-semibold">Preview</h2>
        <p className="mt-2 text-amber-700" role="alert">
          {preview.error}
        </p>
      </section>
    );
  }
  if (preview.status === "loading" || preview.state === null) {
    return (
      <section aria-label="preview" className="text-sm">
        <h2 className="font-semibold">Preview</h2>
        <p className="mt-2 text-slate-500">Loading the engine…</p>
      </section>
    );
  }

  const state = preview.state;
  return (
    <section aria-label="preview" className="flex h-full flex-col text-sm">
      <header className="flex items-baseline gap-3 border-b border-slate-200 pb-2">
        <h2 className="font-semibold">Preview</h2>
        <span className="text-xs text-slate-500">
          the engine the handset runs, in this browser
        </span>
      </header>
      {preview.error !== undefined && (
        <p className="mt-2 text-xs text-amber-700" role="alert">
          {preview.error}
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto py-3">
        <Screen state={state} preview={preview} />
      </div>
      <NavigationBar state={state} preview={preview} />
    </section>
  );
}

type Handle = ReturnType<typeof usePreviewSession>;

function Screen({ state, preview }: { state: PreviewState; preview: Handle }) {
  const inside = state.inside;
  return (
    <div className="space-y-4">
      {state.screen?.title !== null && state.screen?.title !== undefined && (
        <h3 className="text-lg text-blue-800">{state.screen.title}</h3>
      )}
      {inside !== null && (
        <div className="rounded border border-slate-200 p-2">
          <div className="flex items-center gap-2">
            <span className="flex-1 text-base text-blue-800">
              {inside.rowLabel}
            </span>
            <button
              type="button"
              className="text-xs text-blue-700 hover:underline"
              onClick={() => preview.act((s) => s.leave())}
            >
              Back to the list
            </button>
          </div>
          <p className="text-xs text-slate-500">
            Row {inside.across[0]} of {inside.across[1]} · screen{" "}
            {inside.within[0]} of {inside.within[1]}
          </p>
        </div>
      )}
      {state.roster !== null && inside === null && (
        <Roster roster={state.roster} preview={preview} />
      )}
      {state.questions
        .filter((q) => q.relevant)
        .map((q) => (
          <Question key={q.path} question={q} preview={preview} />
        ))}
      {state.screen?.kind === "questions" &&
        state.questions.every((q) => !q.relevant) && (
          <p className="text-xs text-slate-500">
            Nothing on this screen is relevant against the current answers.
          </p>
        )}
    </div>
  );
}

/** A repeat screen (§11.3): the rows, and the controls §2.3 permits. */
function Roster({
  roster,
  preview,
}: {
  roster: PreviewRoster;
  preview: Handle;
}) {
  return (
    <div className="space-y-2" aria-label={`roster ${roster.repeatId}`}>
      <h3 className="text-lg text-blue-800">{roster.title}</h3>
      {roster.rows.length === 0 && (
        <p className="text-xs text-slate-500">
          {roster.canAdd ? "No rows yet" : "This list has no rows"}
        </p>
      )}
      {roster.rows.map((row) => (
        <div
          key={row.instanceId}
          className="flex items-center gap-2 rounded border border-slate-200 bg-slate-50 px-2 py-1"
        >
          <span className="flex-1">{row.label}</span>
          {row.canDelete && (
            <button
              type="button"
              className="text-xs text-red-700 hover:underline"
              aria-label={`delete ${row.label}`}
              onClick={() =>
                preview.act((s) => s.deleteRow(roster.repeatId, row.instanceId))
              }
            >
              Delete
            </button>
          )}
          <button
            type="button"
            className="text-xs text-blue-700 hover:underline"
            aria-label={`open ${row.label}`}
            onClick={() =>
              preview.act((s) => s.enter(roster.repeatId, row.instanceId))
            }
          >
            Open
          </button>
        </div>
      ))}
      {roster.canAdd && (
        <button
          type="button"
          className="rounded bg-slate-900 px-3 py-1 text-xs text-white"
          onClick={() => preview.act((s) => s.addRow(roster.repeatId))}
        >
          {roster.addLabel ?? "Add a row"}
        </button>
      )}
    </div>
  );
}

const NOT_IN_PREVIEW = new Set([
  "image",
  "signature",
  "geopoint",
  "audio",
  "video",
  "file",
]);

function Question({
  question,
  preview,
}: {
  question: PreviewQuestion;
  preview: Handle;
}) {
  const select = useBuilder((s) => s.select);
  const hardError = question.errors.find((e) => e.severity === "error");
  const softError = question.errors.find((e) => e.severity === "warning");
  const shown = hardError ?? softError;
  return (
    <div className="space-y-1">
      <button
        type="button"
        className="text-start font-medium hover:underline"
        onClick={() => select(question.id)}
        title="select in the tree"
      >
        {question.label}
        {question.required && " *"}
      </button>
      <Widget question={question} preview={preview} />
      {shown !== undefined && (
        <p
          className={clsx(
            "text-xs",
            hardError !== undefined ? "text-red-700" : "text-amber-700",
          )}
          role="status"
        >
          {shown.message ??
            (shown.kind === "required"
              ? "This answer is required"
              : "Invalid answer")}
        </p>
      )}
      {question.hint !== null && shown === undefined && (
        <p className="text-xs text-slate-500">{question.hint}</p>
      )}
    </div>
  );
}

function asText(value: EngineValue): string {
  if (value === null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  return JSON.stringify(value);
}

function Widget({
  question,
  preview,
}: {
  question: PreviewQuestion;
  preview: Handle;
}) {
  const disabled = question.readOnly;
  const base =
    "w-full rounded border border-slate-300 px-2 py-1 text-sm disabled:bg-slate-100";
  switch (question.dataType) {
    case "note":
      return null;
    case "text":
      return (
        <input
          aria-label={question.label}
          className={base}
          disabled={disabled}
          value={asText(question.value)}
          onChange={(e) =>
            preview.answer(
              question.path,
              e.target.value === "" ? null : e.target.value,
            )
          }
        />
      );
    case "integer":
    case "decimal":
      return (
        <input
          aria-label={question.label}
          className={base}
          disabled={disabled}
          inputMode={question.dataType === "integer" ? "numeric" : "decimal"}
          value={asText(question.value)}
          onChange={(e) => {
            const text = e.target.value.trim();
            if (text === "") {
              preview.answer(question.path, null);
              return;
            }
            const parsed =
              question.dataType === "integer"
                ? Number.parseInt(text, 10)
                : Number(text);
            // Not a number: the engine's value stays what it was, as the
            // handset's does — a half-typed "3." is not an answer yet.
            if (Number.isFinite(parsed)) preview.answer(question.path, parsed);
          }}
        />
      );
    case "date":
      return (
        <input
          type="date"
          aria-label={question.label}
          className={base}
          disabled={disabled}
          value={asText(question.value)}
          onChange={(e) =>
            preview.answer(
              question.path,
              e.target.value === "" ? null : e.target.value,
            )
          }
        />
      );
    case "select_one":
      return (
        <div
          role="radiogroup"
          aria-label={question.label}
          className="space-y-0.5"
        >
          {question.choices.map((choice) => {
            const selected = question.value === choice.value;
            return (
              <label key={choice.value} className="flex items-center gap-2">
                <input
                  type="radio"
                  name={question.path}
                  disabled={disabled}
                  checked={selected}
                  // Tapping the selected choice again clears it, as on the handset.
                  onClick={() =>
                    preview.answer(
                      question.path,
                      selected ? null : choice.value,
                    )
                  }
                  onChange={() => undefined}
                />
                {choice.label}
              </label>
            );
          })}
        </div>
      );
    case "select_multiple": {
      const current = Array.isArray(question.value)
        ? question.value.filter((v): v is string => typeof v === "string")
        : [];
      return (
        <div role="group" aria-label={question.label} className="space-y-0.5">
          {question.choices.map((choice) => {
            const checked = current.includes(choice.value);
            return (
              <label key={choice.value} className="flex items-center gap-2">
                <input
                  type="checkbox"
                  disabled={disabled}
                  checked={checked}
                  onChange={() => {
                    // Rebuilt in the form's choice order, as the handset does:
                    // §2.1 calls the value order-insensitive.
                    const next = question.choices
                      .map((c) => c.value)
                      .filter((v) =>
                        v === choice.value ? !checked : current.includes(v),
                      );
                    preview.answer(
                      question.path,
                      next.length === 0 ? null : next,
                    );
                  }}
                />
                {choice.label}
              </label>
            );
          })}
        </div>
      );
    }
    default:
      if (NOT_IN_PREVIEW.has(question.dataType)) {
        return (
          <p className="text-xs text-slate-500">
            {question.dataType}: not answerable in preview
          </p>
        );
      }
      return (
        <p className="text-xs text-red-700">
          {question.dataType}: this build has no widget for it
        </p>
      );
  }
}

function NavigationBar({
  state,
  preview,
}: {
  state: PreviewState;
  preview: Handle;
}) {
  const [position, total] = state.progress;
  return (
    <footer className="border-t border-slate-200 pt-2">
      {!state.canFinalize &&
        state.blockers.length > 0 &&
        state.inside === null &&
        !state.hasNext && (
          <p className="mb-1 text-xs text-red-700" role="status">
            Cannot finalize: {state.blockers.length} answer(s) need attention
          </p>
        )}
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="rounded border border-slate-300 px-3 py-1 text-xs disabled:opacity-50"
          disabled={!state.hasPrevious}
          onClick={() => preview.act((s) => s.previous())}
        >
          Previous
        </button>
        <span className="flex-1 text-center text-xs text-slate-500">
          {position} / {total}
        </span>
        {state.hasNext ? (
          <button
            type="button"
            className="rounded bg-slate-900 px-3 py-1 text-xs text-white"
            onClick={() => preview.act((s) => s.next())}
          >
            Next
          </button>
        ) : (
          <FinalizeButton state={state} preview={preview} />
        )}
      </div>
    </footer>
  );
}

function FinalizeButton({
  state,
  preview,
}: {
  state: PreviewState;
  preview: Handle;
}) {
  if (state.canFinalize) {
    return (
      <span
        className="rounded border border-green-700 px-3 py-1 text-xs text-green-800"
        role="status"
      >
        This form would finalize
      </span>
    );
  }
  return (
    <button
      type="button"
      className="rounded bg-slate-900 px-3 py-1 text-xs text-white"
      title="go to the first answer that blocks finalisation"
      onClick={() => preview.act((s) => s.goToFirstBlocking())}
    >
      Finalize
    </button>
  );
}
