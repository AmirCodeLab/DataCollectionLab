/** The sample and its cases for one project (item 2).
 *
 * What this page lists is what the database shows the person looking: the
 * policy `dcp_case_in_scope` decides on their principal, so a programme
 * manager sees the whole sample including the unassigned pool, and a
 * supervisor sees their team's cases and nothing else. No filter here — a
 * filter can be forgotten in one query; a scope cannot.
 *
 * Two things happen on it. A manager uploads the sample: a CSV, a dataset
 * key, and the columns that together identify a row (Form IR §3.1), from
 * which one case is made per row. And the split: a manager assigns cases to
 * teams, a supervisor assigns their team's cases to their enumerators. Both
 * assignments go through the same database function; what it refuses comes
 * back as `outside_your_authority`, and the page shows the reason it was
 * given rather than guessing at one.
 */

import { useMemo, useState, type FormEvent } from "react";
import { Link, getRouteApi } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import {
  assignCases,
  casesQuery,
  meQuery,
  projectListQuery,
  teamsQuery,
  uploadSample,
} from "@/api/queries";
import type { Case, Me, SampleUploadResponse, Team } from "@/api/types";
import { Td, Th } from "@/components/Table";
import { may } from "@/lib/permissions";

const route = getRouteApi("/projects/$projectId/sample");

function refusal(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { reason?: string; message?: string } | string;
    if (typeof detail === "object" && detail?.message) return detail.message;
    return error.message;
  }
  return "Something went wrong.";
}

export function SamplePage() {
  const { projectId } = route.useParams();
  const me = useQuery(meQuery());
  const projects = useQuery(projectListQuery());
  const cases = useQuery(casesQuery(projectId));
  const teams = useQuery(teamsQuery(projectId));

  if (!me.data) return null;
  const project = projects.data?.projects.find((p) => p.id === projectId);
  const canUpload = may(me.data, "sample.upload");
  const canAssign = may(me.data, "sample.assign");

  return (
    <section>
      <p className="text-sm">
        <Link to="/projects" className="text-blue-700 hover:underline">
          Projects
        </Link>
        {project && <> › {project.name}</>}
      </p>
      <h1 className="mt-1 text-xl font-semibold">Sample</h1>
      <p className="mt-1 text-sm text-slate-600">
        One case per sample row. What is listed here is what your scope shows
        you: a programme manager sees the whole sample, a supervisor the cases
        held by their team.
      </p>

      {canUpload && <Upload projectId={projectId} />}

      {cases.isPending && <p className="mt-4 text-slate-500">Loading…</p>}
      {cases.isError && (
        <p role="alert" className="mt-4 text-red-700">
          Could not load the cases: {refusal(cases.error)}
        </p>
      )}
      {cases.data && (
        <Cases
          me={me.data}
          projectId={projectId}
          cases={cases.data.cases}
          teams={teams.data?.teams ?? []}
          canAssign={canAssign}
        />
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// The upload
// ---------------------------------------------------------------------------

function Upload({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [datasetKey, setDatasetKey] = useState("");
  const [keyColumns, setKeyColumns] = useState("");
  const [outcome, setOutcome] = useState<SampleUploadResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (input: { file: File; datasetKey: string; keyColumns: string[] }) =>
      uploadSample(projectId, input),
    onSuccess: (result) => {
      setOutcome(result);
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["cases", projectId] });
    },
    onError: (e) => {
      setOutcome(null);
      setError(refusal(e));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!file) return;
    upload.mutate({
      file,
      datasetKey: datasetKey.trim(),
      keyColumns: keyColumns
        .split(",")
        .map((column) => column.trim())
        .filter((column) => column !== ""),
    });
  };

  const ready =
    file !== null && datasetKey.trim() !== "" && keyColumns.trim() !== "" && !upload.isPending;

  return (
    <form
      onSubmit={submit}
      aria-label="upload a sample"
      className="mt-4 rounded border border-slate-200 bg-slate-50 p-3 text-sm"
    >
      <h2 className="font-medium">Upload a sample</h2>
      <p className="mt-1 text-slate-600">
        A CSV. The key columns, together, identify one row — a settlement, a
        structure and a household, say. Uploading again with the same dataset
        key keeps the cases whose keys are still there, withdraws the ones that
        are gone, and makes new ones.
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1">
          <span>File</span>
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Dataset key</span>
          <input
            value={datasetKey}
            onChange={(event) => setDatasetKey(event.target.value)}
            placeholder="households"
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          <span>Key columns, in order</span>
          <input
            value={keyColumns}
            onChange={(event) => setKeyColumns(event.target.value)}
            placeholder="settlementCode, structureId, hhId"
            className="w-72 rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <button
          type="submit"
          disabled={!ready}
          className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40"
        >
          Upload
        </button>
      </div>
      {outcome && (
        <p role="status" className="mt-2 text-green-800">
          Version {outcome.version} of {outcome.datasetKey}: {outcome.rowCount} rows;{" "}
          {outcome.casesCreated} cases created, {outcome.casesReopened} reopened,{" "}
          {outcome.casesWithdrawn} withdrawn.
          {outcome.warnings.length > 0 && <> {outcome.warnings.join(" ")}</>}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-2 text-red-700">
          {error}
        </p>
      )}
    </form>
  );
}

// ---------------------------------------------------------------------------
// The cases, and the split
// ---------------------------------------------------------------------------

type Holder = { kind: "team"; id: string } | { kind: "person"; id: string };

function Cases({
  me,
  projectId,
  cases,
  teams,
  canAssign,
}: {
  me: Me;
  projectId: string;
  cases: Case[];
  teams: Team[];
  canAssign: boolean;
}) {
  const queryClient = useQueryClient();
  const [selected, setSelected] = useState<ReadonlySet<string>>(new Set());
  const [holder, setHolder] = useState<Holder | null>(null);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Who a case can be given to: the teams this person sees, and the people
  // in them. A supervisor's list is their own team; a manager's is every
  // team in the project. The database checks either way.
  const people = useMemo(() => {
    const seen = new Map<string, string>();
    for (const team of teams) {
      for (const member of team.members) {
        if (member.membershipStatus === "active") seen.set(member.userId, member.displayName);
      }
    }
    return [...seen.entries()].map(([id, name]) => ({ id, name }));
  }, [teams]);

  const assign = useMutation({
    mutationFn: assignCases,
    onSuccess: (result) => {
      setOutcome(`${result.assigned} ${result.assigned === 1 ? "case" : "cases"} assigned.`);
      setError(null);
      setSelected(new Set());
      void queryClient.invalidateQueries({ queryKey: ["cases", projectId] });
    },
    onError: (e) => {
      setOutcome(null);
      setError(refusal(e));
    },
  });

  const toggle = (id: string) => {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  };
  const toggleAll = () => {
    setSelected(selected.size === cases.length ? new Set() : new Set(cases.map((c) => c.id)));
  };

  const submit = () => {
    if (!holder || selected.size === 0) return;
    assign.mutate({
      caseIds: [...selected],
      teamId: holder.kind === "team" ? holder.id : null,
      userId: holder.kind === "person" ? holder.id : null,
    });
  };

  const scopeNote =
    me.scopeKind === "organization"
      ? "You see the whole sample, the unassigned pool included."
      : "You see the cases held by your team.";

  return (
    <div className="mt-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
        <p className="text-slate-600">
          {cases.length} {cases.length === 1 ? "case" : "cases"}. {scopeNote}
        </p>
      </div>

      {canAssign && (
        <div
          role="group"
          aria-label="assign selected cases"
          className="mt-2 flex flex-wrap items-center gap-2 rounded border border-slate-200 p-2 text-sm"
        >
          <span>
            Assign {selected.size} selected to
          </span>
          <select
            aria-label="holder"
            value={holder ? `${holder.kind}:${holder.id}` : ""}
            onChange={(event) => {
              const [kind, id] = event.target.value.split(":");
              setHolder(
                kind === "team" || kind === "person" ? { kind, id: id ?? "" } : null,
              );
            }}
            className="rounded border border-slate-300 px-2 py-1"
          >
            <option value="">— choose —</option>
            {teams.length > 0 && (
              <optgroup label="Teams">
                {teams.map((team) => (
                  <option key={team.id} value={`team:${team.id}`}>
                    {team.name}
                  </option>
                ))}
              </optgroup>
            )}
            {people.length > 0 && (
              <optgroup label="People">
                {people.map((person) => (
                  <option key={person.id} value={`person:${person.id}`}>
                    {person.name}
                  </option>
                ))}
              </optgroup>
            )}
          </select>
          <button
            type="button"
            onClick={submit}
            disabled={!holder || selected.size === 0 || assign.isPending}
            className="rounded bg-slate-900 px-3 py-1 text-white disabled:opacity-40"
          >
            Assign
          </button>
          {outcome && (
            <span role="status" className="text-green-800">
              {outcome}
            </span>
          )}
          {error && (
            <span role="alert" className="text-red-700">
              {error}
            </span>
          )}
        </div>
      )}

      <div className="mt-2 overflow-x-auto">
        <table className="w-full min-w-[48rem] border-collapse text-sm">
          <thead>
            <tr className="border-b border-slate-300 text-slate-600">
              {canAssign && (
                <Th>
                  <input
                    type="checkbox"
                    aria-label="select all"
                    checked={cases.length > 0 && selected.size === cases.length}
                    onChange={toggleAll}
                  />
                </Th>
              )}
              <Th>Case</Th>
              <Th>Dataset</Th>
              <Th>Status</Th>
              <Th>Team</Th>
              <Th>Person</Th>
              <Th>Collected</Th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr key={c.id} className="border-b border-slate-100">
                {canAssign && (
                  <Td>
                    <input
                      type="checkbox"
                      aria-label={`select ${c.caseKey ?? c.id}`}
                      checked={selected.has(c.id)}
                      onChange={() => toggle(c.id)}
                    />
                  </Td>
                )}
                <Td>
                  <span className="font-mono">{c.caseKey ?? c.id}</span>
                  <Summary data={c.data} />
                </Td>
                <Td>{c.datasetKey ?? ""}</Td>
                <Td>
                  <code>{c.status}</code>
                </Td>
                <Td>{c.holder.teamName ?? <span className="text-slate-400">unassigned</span>}</Td>
                <Td>{c.holder.userName ?? <span className="text-slate-400">—</span>}</Td>
                <Td>{c.submissions}</Td>
              </tr>
            ))}
          </tbody>
        </table>
        {cases.length === 0 && (
          <p className="py-6 text-slate-500">
            No cases in your scope.
          </p>
        )}
      </div>
    </div>
  );
}

/** The sample row behind a case, in a line: the first few non-key values. */
function Summary({ data }: { data: Record<string, unknown> }) {
  const shown = Object.entries(data)
    .filter(([key, value]) => key !== "case_key" && value !== null && value !== "")
    .slice(0, 4);
  if (shown.length === 0) return null;
  return (
    <div className="text-xs text-slate-500">
      {shown.map(([key, value]) => `${key}: ${String(value)}`).join(" · ")}
    </div>
  );
}
