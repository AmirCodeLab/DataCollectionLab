/** View, download, copy, or replace the IR — the floor under the editor
 *  (scope §1).
 *
 * The IR is JSON and the API accepts it, so an author who needs something the
 * builder cannot express downloads the document, edits it, and puts it back.
 * That is first-class here, not a hidden route. Putting it back goes through
 * `POST /forms/compile` first so a bad document is refused with §10.1's own
 * reason — and then, because a draft is allowed to hold a form that does not
 * compile, the author may replace anyway and the plan will say why.
 *
 * Nothing pasted is modified on the way in. `asFormIr` refuses a document
 * whose header it cannot edit rather than reshaping it, and fills only
 * absent header keys.
 */

import { useRef, useState, type ChangeEvent } from "react";

import { ApiError } from "@/api/client";
import { compileForm } from "@/api/queries";
import { refusalsFrom } from "@/builder/compile";
import { asFormIr, type FormIr } from "@/builder/ir";
import { useBuilder } from "@/builder/store";

type Panel = "view" | "replace" | null;

export function IrMenu() {
  const ir = useBuilder((s) => s.ir);
  const [panel, setPanel] = useState<Panel>(null);
  const [copied, setCopied] = useState(false);

  if (ir === null) return null;

  const json = JSON.stringify(ir, null, 2);
  const canDownload = typeof URL.createObjectURL === "function";

  const download = () => {
    if (!canDownload) return;
    const blob = new Blob([json], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${ir.formId || "form"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  };

  const copy = () => {
    const clipboard = navigator.clipboard as Clipboard | undefined;
    if (clipboard === undefined) return;
    clipboard
      .writeText(json)
      .then(() => setCopied(true))
      .catch(() => setCopied(false));
  };

  const toggle = (next: Panel) => setPanel((p) => (p === next ? null : next));

  return (
    <span className="relative inline-flex items-center gap-2 text-xs">
      <span className="text-slate-500">IR:</span>
      <button type="button" className={button} onClick={() => toggle("view")}>
        View
      </button>
      <button
        type="button"
        className={button}
        onClick={download}
        disabled={!canDownload}
        title={canDownload ? undefined : "downloads are not available here"}
      >
        Download
      </button>
      <button type="button" className={button} onClick={copy}>
        {copied ? "Copied" : "Copy"}
      </button>
      <button
        type="button"
        className={button}
        onClick={() => toggle("replace")}
      >
        Replace…
      </button>
      {panel === "view" && (
        <div className={panelClass} role="dialog" aria-label="the form's IR">
          <pre className="max-h-[60vh] overflow-auto whitespace-pre text-[11px]">
            {json}
          </pre>
        </div>
      )}
      {panel === "replace" && (
        <div className={panelClass} role="dialog" aria-label="replace the IR">
          <ReplacePanel onDone={() => setPanel(null)} />
        </div>
      )}
    </span>
  );
}

const button =
  "rounded border border-slate-300 px-2 py-0.5 text-slate-700 hover:bg-slate-50 disabled:opacity-50";
const panelClass =
  "absolute end-0 top-full z-10 mt-1 w-[36rem] max-w-[90vw] rounded border border-slate-300 bg-white p-3 text-start shadow-lg";

type Check =
  | { state: "idle" }
  | { state: "checking" }
  | { state: "parse-error"; message: string }
  | { state: "not-a-form"; reason: string }
  | { state: "refused"; reasons: string[]; ir: FormIr }
  | { state: "failed"; message: string };

function ReplacePanel({ onDone }: { onDone: () => void }) {
  const replace = useBuilder((s) => s.replace);
  const [text, setText] = useState("");
  const [check, setCheck] = useState<Check>({ state: "idle" });
  const fileInput = useRef<HTMLInputElement>(null);

  const onFile = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file === undefined) return;
    file
      .text()
      .then((contents) => setText(contents))
      .catch((error: unknown) =>
        setCheck({
          state: "failed",
          message: error instanceof Error ? error.message : String(error),
        }),
      );
  };

  const submit = async () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(text);
    } catch (error: unknown) {
      setCheck({
        state: "parse-error",
        message: error instanceof Error ? error.message : String(error),
      });
      return;
    }
    const opened = asFormIr(parsed);
    if ("reason" in opened) {
      setCheck({ state: "not-a-form", reason: opened.reason });
      return;
    }
    setCheck({ state: "checking" });
    try {
      // Compile first, so a bad document is refused with the server's own
      // reason before it lands in the draft.
      await compileForm(opened.ir);
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 422) {
        setCheck({
          state: "refused",
          reasons: refusalsFrom(error),
          ir: opened.ir,
        });
      } else {
        setCheck({
          state: "failed",
          message: error instanceof Error ? error.message : String(error),
        });
      }
      return;
    }
    replace(opened.ir);
    onDone();
  };

  return (
    <div className="space-y-2">
      <p className="text-slate-600">
        Paste a Form IR document, or choose a file. It is compiled first; if the
        server refuses it you see its reasons and may still replace the draft
        with it.
      </p>
      <textarea
        aria-label="IR to replace the draft with"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setCheck({ state: "idle" });
        }}
        className="h-40 w-full rounded border border-slate-300 p-2 font-mono text-[11px]"
        spellCheck={false}
      />
      <div className="flex flex-wrap items-center gap-2">
        <input
          ref={fileInput}
          type="file"
          accept="application/json,.json"
          aria-label="upload an IR file"
          onChange={onFile}
          className="text-xs"
        />
        <button
          type="button"
          className={button}
          disabled={text.trim() === "" || check.state === "checking"}
          onClick={() => void submit()}
        >
          {check.state === "checking" ? "Checking…" : "Check and replace"}
        </button>
        <button type="button" className={button} onClick={onDone}>
          Cancel
        </button>
      </div>
      {check.state === "parse-error" && (
        <p className="text-red-700">Not JSON: {check.message}</p>
      )}
      {check.state === "not-a-form" && (
        <p className="text-red-700">
          Cannot open this in the editor: {check.reason}
        </p>
      )}
      {check.state === "failed" && (
        <p className="text-red-700">Could not check: {check.message}</p>
      )}
      {check.state === "refused" && (
        <div className="space-y-1">
          <p className="text-red-700">
            The server refuses this document. Its reasons, as sent:
          </p>
          <ul
            className="list-disc ps-5 text-red-700"
            aria-label="refusal reasons"
          >
            {check.reasons.map((reason, i) => (
              <li key={i} className="whitespace-pre-wrap">
                {reason}
              </li>
            ))}
          </ul>
          <button
            type="button"
            className={button}
            onClick={() => {
              replace(check.ir);
              onDone();
            }}
          >
            Replace anyway — the draft will hold it, and the plan will say why
            it does not compile
          </button>
        </div>
      )}
    </div>
  );
}
