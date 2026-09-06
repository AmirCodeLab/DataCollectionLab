/** The screen plan the server returned: what an enumerator sees, where you
 *  check (scope §3).
 *
 * The builder does not derive a screen plan. It asks for one and renders it.
 * §11.1's partition has six rules and three of them surprise people — a
 * calculate produces no screen, a field-list flattens nested plain groups, a
 * repeat is exactly one screen at any instance count — and a console that
 * reimplemented them would be a third implementation of the screen plan,
 * unreachable by any vector. So between an edit and the next answer this
 * pane shows the old plan, dimmed, with its original numbers, and says it is
 * stale. It never renumbers after a delete, never greys a screen, never
 * "just fixes the badge".
 *
 * Selection is shared with the tree; editing is not. Clicking a question
 * here selects it there, and nothing here is editable.
 */

import clsx from "clsx";

import type { CompileResponse, ScreenSummary } from "@/api/types";
import { displayLabel, find, type FormIr } from "@/builder/ir";
import { useBuilder, type CompileState } from "@/builder/store";

export function PlanPane() {
  const compile = useBuilder((s) => s.compile);
  const ir = useBuilder((s) => s.ir);
  const select = useBuilder((s) => s.select);
  const selectedId = useBuilder((s) => s.selectedId);

  if (ir === null) return null;

  const dimmed = compile.status !== "current" && compile.result !== null;

  return (
    <div className="text-sm">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-slate-500">
        Screen plan
      </h2>
      <Status compile={compile} />
      {compile.result !== null && (
        <div
          className={clsx("mt-3", dimmed && "opacity-50")}
          aria-label={dimmed ? "screen plan (stale)" : "screen plan"}
          data-stale={dimmed ? "true" : undefined}
        >
          <Warnings warnings={compile.result.warnings} />
          <Screens
            result={compile.result}
            ir={ir}
            selectedId={selectedId}
            onSelect={select}
          />
          <p className="mt-3 text-xs text-slate-500">
            {compile.result.fieldCount} fields ·{" "}
            {compile.result.evaluationOrder.length} in evaluation order
          </p>
        </div>
      )}
    </div>
  );
}

function Status({ compile }: { compile: CompileState }) {
  switch (compile.status) {
    case "idle":
      return <p className="mt-1 text-xs text-slate-500">Not compiled yet.</p>;
    case "pending":
      return (
        <p className="mt-1 text-xs text-slate-500" role="status">
          Asking the server…
        </p>
      );
    case "current":
      return (
        <p className="mt-1 text-xs text-green-700" role="status">
          Current for this version of the form.
        </p>
      );
    case "stale":
      return (
        <p className="mt-1 text-xs text-amber-700" role="status">
          This plan is for an earlier version of the form — a new one is on its
          way.
        </p>
      );
    case "refused":
      return (
        <div className="mt-1" role="status">
          <p className="text-xs text-red-700">
            The server refuses this form. Its reasons, as sent:
          </p>
          <ul className="mt-1 list-disc ps-5 text-xs text-red-700">
            {compile.refusals.map((reason, i) => (
              <li key={i} className="whitespace-pre-wrap">
                {reason}
              </li>
            ))}
          </ul>
          {compile.result !== null && (
            <p className="mt-1 text-xs text-slate-500">
              The plan below is for the last version that compiled.
            </p>
          )}
        </div>
      );
    case "failed":
      return (
        <p className="mt-1 text-xs text-red-700" role="status">
          Could not compile: {compile.failure ?? "unknown failure"}
        </p>
      );
  }
}

/** Whatever the engine sent, and nothing else. When the engine gains the
 *  three warnings known defect 17 is about, they appear here unchanged. */
function Warnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;
  return (
    <ul
      className="mb-3 list-disc ps-5 text-xs text-amber-800"
      aria-label="warnings"
    >
      {warnings.map((warning, i) => (
        <li key={i} className="whitespace-pre-wrap">
          {warning}
        </li>
      ))}
    </ul>
  );
}

interface ScreensProps {
  result: CompileResponse;
  ir: FormIr;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function Screens({ result, ir, selectedId, onSelect }: ScreensProps) {
  const screens = result.screens ?? [];
  if (screens.length === 0) {
    return (
      <p className="text-xs text-slate-500">No screens: nothing is asked.</p>
    );
  }
  return (
    <ol className="space-y-2" aria-label="screens">
      {screens.map((screen) => (
        <li key={screen.index} className="rounded border border-slate-200 p-2">
          <ScreenHeading screen={screen} prefix="Screen" />
          {screen.kind === "repeat" ? (
            <InstancePlan
              screens={
                screen.repeatId
                  ? (result.instancePlans?.[screen.repeatId] ?? [])
                  : []
              }
              ir={ir}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          ) : (
            <Questions
              ids={screen.questionIds}
              ir={ir}
              selectedId={selectedId}
              onSelect={onSelect}
            />
          )}
        </li>
      ))}
    </ol>
  );
}

function ScreenHeading({
  screen,
  prefix,
}: {
  screen: ScreenSummary;
  prefix: string;
}) {
  const what =
    screen.kind === "repeat"
      ? `roster ${screen.repeatId ?? ""}`
      : screen.groupId
        ? `questions (${screen.groupId})`
        : "questions";
  return (
    <p className="text-xs font-medium text-slate-700">
      {prefix} {screen.index} · {what}
    </p>
  );
}

/** A repeat screen's instance plan, nested once. §11.1 makes a deeper level
 *  impossible — a repeat cannot hold a repeat — so this does not recurse. */
function InstancePlan(
  props: Omit<ScreensProps, "result"> & { screens: ScreenSummary[] },
) {
  const { screens, ir, selectedId, onSelect } = props;
  if (screens.length === 0) {
    return (
      <p className="mt-1 text-xs text-slate-500">
        One screen holding the row list; each row is entered and left.
      </p>
    );
  }
  return (
    <ol
      className="mt-1 space-y-1 border-s border-slate-200 ps-3"
      aria-label="row screens"
    >
      {screens.map((screen) => (
        <li key={screen.index}>
          <ScreenHeading screen={screen} prefix="Row screen" />
          <Questions
            ids={screen.questionIds}
            ir={ir}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        </li>
      ))}
    </ol>
  );
}

function Questions({
  ids,
  ir,
  selectedId,
  onSelect,
}: {
  ids: string[];
  ir: FormIr;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <ul className="mt-1 space-y-0.5">
      {ids.map((id) => {
        // Display, not recomputation: the plan's ids are the server's; the
        // label beside one is read from the document as it is now, and an id
        // the document no longer holds is shown as exactly that.
        const path = find(ir, id);
        return (
          <li key={id}>
            <button
              type="button"
              onClick={() => onSelect(id)}
              className={clsx(
                "w-full rounded px-1 py-0.5 text-start text-xs hover:bg-slate-100",
                selectedId === id && "bg-blue-50 text-blue-900",
              )}
            >
              {path === null ? (
                <>
                  <code>{id}</code>{" "}
                  <span className="text-amber-700">
                    — no longer in the form
                  </span>
                </>
              ) : (
                <>
                  {displayLabel(path.node, ir)}{" "}
                  <code className="text-slate-500">{id}</code>
                </>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}
