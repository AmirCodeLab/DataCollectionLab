/** Projects, their security mode, and whether they can actually receive data. */

import { Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { projectListQuery } from "@/api/queries";
import type { ProjectSummary } from "@/api/types";
import { Td, Th } from "@/components/Table";
import { formatTimestamp } from "@/lib/format";

export function ProjectsPage() {
  const projects = useQuery(projectListQuery());

  return (
    <section>
      <h1 className="text-xl font-semibold">Projects</h1>
      <p className="mt-1 text-sm text-slate-600">
        A project&apos;s security mode is fixed at creation — changing it would
        mean re-encrypting or decrypting everything already collected, which is
        the point of having chosen it.
      </p>

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
                  <Td className="whitespace-nowrap text-xs">
                    {formatTimestamp(project.createdAt)}
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
          {projects.data.projects.length === 0 && (
            <p className="py-6 text-slate-500">
              No projects. Run <code>scripts/seed_dev.py</code>.
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
