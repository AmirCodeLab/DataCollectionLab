import { Link, Outlet } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { healthQuery } from "@/api/queries";

export function Layout() {
  const health = useQuery(healthQuery());

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-slate-200 px-6 py-3">
        <Link to="/submissions" className="text-lg font-semibold">
          DCP Console
        </Link>
        <nav className="text-sm text-slate-600">
          <Link
            to="/submissions"
            className="hover:underline"
            activeProps={{ className: "font-medium text-slate-900" }}
          >
            Submissions
          </Link>
          <Link
            to="/projects"
            className="ms-4 hover:underline"
            activeProps={{ className: "font-medium text-slate-900" }}
          >
            Projects
          </Link>
        </nav>
        <span className="ms-auto text-xs text-slate-500">
          API:{" "}
          {health.isPending && <span>checking…</span>}
          {health.isError && <span className="text-red-600">unreachable</span>}
          {health.data && (
            <span className="text-green-700">
              {health.data.status} ({health.data.environment})
            </span>
          )}
        </span>
      </header>
      <main className="px-6 py-5">
        <Outlet />
      </main>
    </div>
  );
}
