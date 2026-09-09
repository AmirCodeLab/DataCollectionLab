/** The frame every screen sits in — and the gate in front of all of them.
 *
 * `meQuery` decides what renders: nothing until it answers; the sign-in form
 * when it says there is no session; the screen, with a nav that offers only
 * what this person's permissions allow, when there is one. A screen checks a
 * permission by name from the contract's `PERMISSIONS`, never a role, so the
 * first custom role does not break the UI (pilot scope §3.5).
 *
 * The gate is a courtesy, not the guarantee: every request the screens make
 * is refused by the server without a session, and the rows a signed-in person
 * sees are the database's decision. What this does is put the sign-in form in
 * front of a person instead of a page of failed requests.
 */

import { useEffect } from "react";
import { Link, Outlet, useLocation, useNavigate } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { SIGNED_OUT_EVENT } from "@/api/client";
import { healthQuery, logout, ME_QUERY_KEY, meQuery } from "@/api/queries";
import type { Permission } from "@/api/types";
import { may } from "@/lib/permissions";

/** What each section needs: any one of these opens it. */
const NAV: ReadonlyArray<{ to: "/submissions" | "/projects" | "/forms"; label: string; any: Permission[] }> = [
  { to: "/submissions", label: "Submissions", any: ["submission.view"] },
  {
    to: "/projects",
    label: "Projects",
    any: ["project.manage", "form.edit", "form.publish", "sample.upload", "team.manage"],
  },
  { to: "/forms", label: "Forms", any: ["form.edit", "form.publish", "submission.view"] },
];

export function Layout() {
  const health = useQuery(healthQuery());
  const me = useQuery(meQuery());
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const onLoginPage = location.pathname === "/login";

  // A 401 from anywhere means the session is gone — revoked, expired, or the
  // person deactivated under the page. Drop what we knew and let the gate
  // below send them to sign in.
  useEffect(() => {
    const signedOut = () => {
      // Only a session we knew about can be lost. The sign-in page's own
      // `me` probe answers 401 too, and re-asking on every one of those
      // would ask forever.
      if (queryClient.getQueryData(ME_QUERY_KEY)) {
        queryClient.setQueryData(ME_QUERY_KEY, null);
      }
    };
    window.addEventListener(SIGNED_OUT_EVENT, signedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, signedOut);
  }, [queryClient]);

  const signOut = useMutation({
    mutationFn: logout,
    onSettled: () => {
      queryClient.setQueryData(ME_QUERY_KEY, null);
      void navigate({ to: "/login" });
    },
  });

  const signedIn = me.data ?? null;

  useEffect(() => {
    if (!onLoginPage && !me.isPending && signedIn === null) {
      void navigate({ to: "/login" });
    }
    if (onLoginPage && signedIn !== null) {
      void navigate({ to: "/submissions", search: {} });
    }
  }, [onLoginPage, me.isPending, signedIn, navigate]);

  return (
    <div className="min-h-screen bg-white text-slate-900">
      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-1 border-b border-slate-200 px-6 py-3">
        <Link to="/submissions" className="text-lg font-semibold">
          DCP Console
        </Link>
        {signedIn && (
          <nav className="text-sm text-slate-600">
            {NAV.filter((item) => may(signedIn, ...item.any)).map((item, index) => (
              <Link
                key={item.to}
                to={item.to}
                className={index === 0 ? "hover:underline" : "ms-4 hover:underline"}
                activeProps={{ className: "font-medium text-slate-900" }}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        )}
        <span className="ms-auto flex items-baseline gap-4 text-xs text-slate-500">
          {signedIn && (
            <span>
              {signedIn.displayName || signedIn.username}{" "}
              <button
                type="button"
                onClick={() => signOut.mutate()}
                className="ms-1 underline hover:text-slate-900"
              >
                Sign out
              </button>
            </span>
          )}
          <span>
            API:{" "}
            {health.isPending && <span>checking…</span>}
            {health.isError && <span className="text-red-600">unreachable</span>}
            {health.data && (
              <span className="text-green-700">
                {health.data.status} ({health.data.environment})
              </span>
            )}
          </span>
        </span>
      </header>
      <main className="px-6 py-5">
        {onLoginPage || signedIn ? (
          <Outlet />
        ) : me.isPending ? (
          <p className="text-sm text-slate-500">Checking your session…</p>
        ) : null}
      </main>
    </div>
  );
}
