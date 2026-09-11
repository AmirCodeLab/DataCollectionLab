/** Projects, their security mode, and whether they can actually receive data. */

import { useState } from "react";
import { Link } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { createProject, meQuery, projectListQuery } from "@/api/queries";
import { SECURITY_MODES, type ProjectSummary, type SecurityMode } from "@/api/types";
import { Td, Th } from "@/components/Table";
import { formatTimestamp } from "@/lib/format";
import { may } from "@/lib/permissions";

export function ProjectsPage() {
  const projects = useQuery(projectListQuery());
  const me = useQuery(meQuery());

  return (
    <section>
      <h1 className="text-xl font-semibold">Projects</h1>
      <p className="mt-1 text-sm text-slate-600">
        A project&apos;s security mode is fixed at creation — changing it would
        mean re-encrypting or decrypting everything already collected, which is
        the point of having chosen it.
      </p>

      {me.data && may(me.data, "project.manage") && <NewProject />}

      {projects.isPending && <p className="mt-4 text-slate-500">Loading…</p>}
      {projects.isError && (
        <p className="mt-4 text-red-600">
          Could not load projects: {String(projects.error)}
        </p>
      )}

      {projects.data && (
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[44rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-slate-600">
                <Th>Name</Th>
                <Th>Security mode</Th>
                <Th>Recipient keys</Th>
                <Th>Sample</Th>
                <Th>Monitoring</Th>
                <Th>Created</Th>
              </tr>
            </thead>
            <tbody>
              {projects.data.projects.map((project) => (
                <tr key={project.id} className="border-b border-slate-100">
                  <Td>
                    <Link
                      to="/projects/$projectId/keys"
                      params={{ projectId: project.id }}
                      className="text-blue-700 hover:underline"
                    >
                      {project.name}
                    </Link>
                    <div className="font-mono text-xs text-slate-500">
                      {project.slug}
                    </div>
                  </Td>
                  <Td>
                    <code>{project.securityMode}</code>
                  </Td>
                  <Td>
                    <KeyCount project={project} />
                  </Td>
                  <Td>
                    <Link
                      to="/projects/$projectId/sample"
                      params={{ projectId: project.id }}
                      className="text-blue-700 hover:underline"
                    >
                      cases
                    </Link>
                  </Td>
                  <Td>
                    <Link
                      to="/projects/$projectId/monitoring"
                      params={{ projectId: project.id }}
                      className="text-blue-700 hover:underline"
                    >
                      progress
                    </Link>
                  </Td>
                  <Td className="whitespace-nowrap text-xs">
                    {formatTimestamp(project.createdAt)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {projects.data.projects.length === 0 && (
            <p className="py-6 text-slate-500">
              {/* Not "run the dev seed". Until gate 1 that was the only way
                  a project could exist, so it was true; it is now advice that
                  would have a customer running a script which refuses outside
                  development and publishes a password. Found by the run, on an
                  organisation no seed made. */}
              No projects yet.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function KeyCount({ project }: { project: ProjectSummary }) {
  if (project.securityMode === "standard") {
    // Recipient keys are inert in standard mode; showing a count as a problem
    // would be a warning about nothing.
    return <span className="text-slate-500">not used in this mode</span>;
  }
  if (project.activeKeyCount === 0) {
    return (
      <span className="text-amber-700">
        none — devices cannot sync until one exists
      </span>
    );
  }
  return <span>{project.activeKeyCount}</span>;
}


/** Creating a project, and the two things it settles that cannot be changed.
 *
 * The security mode is fixed at creation, and the slug is what URLs are built
 * from — so both are stated here rather than discovered later.
 *
 * There is deliberately no "new organisation" anywhere in this console. An
 * organisation cannot be created under row-level security, because there is no
 * principal until it exists, so the act belongs to an operator on the server
 * (`scripts/provision.py`) and not to a screen.
 */
function NewProject() {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [securityMode, setSecurityMode] = useState<SecurityMode>("standard");
  const [refusal, setRefusal] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => createProject({ name, slug, securityMode }),
    onSuccess: () => {
      setOpen(false);
      setName("");
      setSlug("");
      setRefusal(null);
      void client.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: (error: unknown) => {
      const detail = (error as { detail?: { message?: string } })?.detail;
      setRefusal(detail?.message ?? String(error));
    },
  });

  if (!open) {
    return (
      <button
        type="button"
        className="mt-4 rounded bg-slate-900 px-3 py-2 text-sm text-white"
        onClick={() => setOpen(true)}
      >
        New project
      </button>
    );
  }

  return (
    <div className="mt-4 max-w-xl rounded border border-slate-200 p-3">
      <label className="block text-sm">
        <span className="font-medium">Name</span>
        <input
          className="mt-1 block w-full rounded border border-slate-300 p-2"
          value={name}
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label className="mt-3 block text-sm">
        <span className="font-medium">Slug</span>
        <span className="mt-1 block text-slate-600">
          Lowercase, no spaces. URLs are built from it and it does not change.
        </span>
        <input
          className="mt-1 block w-full rounded border border-slate-300 p-2 font-mono"
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
        />
      </label>
      <label className="mt-3 block text-sm">
        <span className="font-medium">Security mode</span>
        <span className="mt-1 block text-slate-600">
          Fixed at creation. <code>standard</code> stores answers the server can
          read; the other two do not, and then a lost key is lost data — read
          docs/key-custody.md before choosing one.
        </span>
        <select
          className="mt-1 block w-full max-w-xs rounded border border-slate-300 p-2"
          value={securityMode}
          onChange={(event) => setSecurityMode(event.target.value as SecurityMode)}
        >
          {SECURITY_MODES.map((mode) => (
            <option key={mode} value={mode}>
              {mode}
            </option>
          ))}
        </select>
      </label>
      <p className="mt-3 text-sm text-slate-600">
        Development, staging and production environments are created with it.
      </p>
      <div className="mt-3 flex gap-2">
        <button
          type="button"
          className="rounded bg-slate-900 px-3 py-2 text-sm text-white disabled:bg-slate-400"
          disabled={create.isPending || name.trim() === "" || slug.trim() === ""}
          onClick={() => create.mutate()}
        >
          {create.isPending ? "Creating…" : "Create project"}
        </button>
        <button
          type="button"
          className="rounded border border-slate-300 px-3 py-2 text-sm"
          onClick={() => setOpen(false)}
        >
          Cancel
        </button>
      </div>
      {refusal && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {refusal}
        </p>
      )}
    </div>
  );
}
