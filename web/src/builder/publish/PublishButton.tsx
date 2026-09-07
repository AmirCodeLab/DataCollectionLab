/** Publish the draft through the one route into `form_version` (scope §6).
 *
 * `POST /forms/versions` with the document as it is in this editor — the
 * same route, the same `check_publishable`, as an XLSForm import. There is
 * no promotion of the draft row and no second path; a draft never becomes a
 * version except this way. What the server refuses is shown as it was sent,
 * one violation per line, never rephrased and never composed here.
 */

import { useCallback, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { publishVersion } from "@/api/queries";
import {
  ENVIRONMENT_KINDS,
  type EnvironmentKind,
  type PublishVersionResponse,
} from "@/api/types";
import { refusalsFrom } from "@/builder/compile";
import { useDismiss } from "@/builder/dismiss";
import type { FormIr } from "@/builder/ir";
import { useBuilder } from "@/builder/store";
import { nextVersion } from "./version";

export interface PublishButtonProps {
  projectId: string;
  /** The version numbers already published for this form, from the list. */
  publishedVersions?: number[];
}

type Outcome =
  | { state: "idle" }
  | { state: "publishing" }
  | { state: "published"; response: PublishVersionResponse }
  /** A refusal is of one document; once that document changes it is history. */
  | { state: "refused"; violations: string[]; forIr: FormIr }
  | { state: "failed"; message: string; forIr: FormIr };

export function PublishButton({
  projectId,
  publishedVersions = [],
}: PublishButtonProps) {
  const ir = useBuilder((s) => s.ir);
  const saveStatus = useBuilder((s) => s.save.status);
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [deployTo, setDeployTo] = useState<EnvironmentKind[]>([]);
  const [publishedBy, setPublishedBy] = useState("");
  const [outcome, setOutcome] = useState<Outcome>({ state: "idle" });
  const container = useRef<HTMLSpanElement>(null);
  const close = useCallback(() => setOpen(false), []);
  useDismiss(open, container, close);

  if (ir === null) return null;
  // A refusal or failure shown against a document the author has since
  // edited would be a verdict on a form that no longer exists.
  const current: Outcome =
    (outcome.state === "refused" || outcome.state === "failed") &&
    outcome.forIr !== ir
      ? { state: "idle" }
      : outcome;
  const version = nextVersion(ir.version, publishedVersions);
  const form = version === ir.version ? ir : { ...ir, version };

  const toggleEnvironment = (kind: EnvironmentKind) =>
    setDeployTo((current) =>
      current.includes(kind)
        ? current.filter((k) => k !== kind)
        : [...current, kind],
    );

  const publish = async () => {
    setOutcome({ state: "publishing" });
    try {
      const response = await publishVersion({
        projectId,
        form,
        deployTo,
        ...(publishedBy.trim() === ""
          ? {}
          : { publishedBy: publishedBy.trim() }),
      });
      setOutcome({ state: "published", response });
      // The draft carries the number it became, so the next publish counts
      // on from here and a reopen shows what is out there.
      if (form !== ir) useBuilder.getState().editForm({ version });
      await queryClient.invalidateQueries({ queryKey: ["forms"] });
    } catch (error: unknown) {
      if (error instanceof ApiError && error.status === 422) {
        setOutcome({
          state: "refused",
          violations: refusalsFrom(error),
          forIr: form,
        });
      } else {
        setOutcome({
          state: "failed",
          message: error instanceof Error ? error.message : String(error),
          forIr: form,
        });
      }
    }
  };

  return (
    <span ref={container} className="relative inline-block text-xs">
      <button
        type="button"
        className="rounded bg-slate-900 px-3 py-1 text-sm text-white hover:bg-slate-700"
        onClick={() => setOpen((o) => !o)}
      >
        Publish…
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="publish this form"
          className="absolute end-0 top-full z-10 mt-1 w-[26rem] max-w-[90vw] rounded border border-slate-300 bg-white p-3 text-start shadow-lg"
        >
          <p className="text-slate-600">
            Publishes the form as it is in this editor as{" "}
            <strong>version {version}</strong>, through the same checks an
            import runs.
          </p>
          {saveStatus !== "clean" && (
            <p className="mt-2 text-amber-700" role="note">
              Unsaved changes will be published as they are here; the draft on
              the server is older.
            </p>
          )}
          <fieldset className="mt-2">
            <legend className="text-slate-600">Deploy to</legend>
            {ENVIRONMENT_KINDS.map((kind) => (
              <label key={kind} className="me-3 inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={deployTo.includes(kind)}
                  onChange={() => toggleEnvironment(kind)}
                />
                {kind}
              </label>
            ))}
          </fieldset>
          <label className="mt-2 block">
            <span className="text-slate-600">Published by (optional)</span>
            <input
              value={publishedBy}
              onChange={(e) => setPublishedBy(e.target.value)}
              className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            />
          </label>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-50"
              disabled={outcome.state === "publishing"}
              onClick={() => void publish()}
            >
              {outcome.state === "publishing" ? "Publishing…" : "Publish"}
            </button>
            <button
              type="button"
              className="rounded border border-slate-300 px-3 py-1"
              onClick={() => setOpen(false)}
            >
              Close
            </button>
          </div>
          <Result outcome={current} />
        </div>
      )}
    </span>
  );
}

function Result({ outcome }: { outcome: Outcome }) {
  switch (outcome.state) {
    case "idle":
    case "publishing":
      return null;
    case "published": {
      const r = outcome.response;
      return (
        <div className="mt-3 text-green-800" role="status">
          <p>
            {r.created ? "Published" : "Already published"} as version{" "}
            {r.version}.
            {r.deployments.length > 0 &&
              ` Deployed to ${r.deployments.join(", ")}.`}
          </p>
          {r.warnings.length > 0 && (
            <ul
              className="mt-1 list-disc ps-5 text-amber-800"
              aria-label="warnings"
            >
              {r.warnings.map((w, i) => (
                <li key={i} className="whitespace-pre-wrap">
                  {w}
                </li>
              ))}
            </ul>
          )}
        </div>
      );
    }
    case "refused":
      return (
        <div className="mt-3 text-red-700" role="status">
          <p>Refused. The server's reasons, as sent:</p>
          <ul className="mt-1 list-disc ps-5" aria-label="violations">
            {outcome.violations.map((v, i) => (
              <li key={i} className="whitespace-pre-wrap">
                {v}
              </li>
            ))}
          </ul>
        </div>
      );
    case "failed":
      return (
        <p className="mt-3 text-red-700" role="status">
          Could not publish: {outcome.message}
        </p>
      );
  }
}
