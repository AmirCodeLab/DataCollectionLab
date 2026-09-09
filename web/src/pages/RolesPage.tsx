/** Roles: a set of permissions plus a scope (pilot scope §3.5).
 *
 * The permissions offered are the contract's `PERMISSIONS`, which is the
 * database's closed set. The ones this person may put on a role are the ones
 * they hold — a checkbox they lack is disabled here and refused by the
 * database (010_people.sql §4) — and the standard roles are read-only both
 * here and there. A role editable on this screen is a role the policy reads.
 */

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import { createRole, meQuery, rolesQuery, setRolePermissions } from "@/api/queries";
import { GRANT_SCOPES, PERMISSIONS, type GrantScope, type Me, type Permission, type Role } from "@/api/types";

function refusal(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { message?: string } | string;
    if (typeof detail === "object" && detail?.message) return detail.message;
    return error.message;
  }
  return "Something went wrong.";
}

export function RolesPage() {
  const me = useQuery(meQuery());
  const roles = useQuery(rolesQuery());
  if (!me.data) return null;
  if (roles.isPending) return <p className="text-sm text-slate-500">Loading roles…</p>;
  if (roles.isError) return <p className="text-sm text-red-700">{refusal(roles.error)}</p>;

  return (
    <div className="flex flex-col gap-8">
      <section>
        <h1 className="text-xl font-semibold">Roles</h1>
        <p className="mt-1 text-sm text-slate-600">
          A role is a set of permissions plus a scope. You can give a role only the permissions
          you hold yourself, and the standard roles cannot be changed.
        </p>
        <ul className="mt-4 flex flex-col gap-4">
          {roles.data.roles.map((role) => (
            <RoleCard key={role.id} role={role} me={me.data} />
          ))}
        </ul>
      </section>
      <NewRole me={me.data} />
    </div>
  );
}

function RoleCard({ role, me }: { role: Role; me: Me }) {
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: (permissions: Permission[]) => setRolePermissions(role.id, { permissions }),
    onSuccess: () => {
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
    onError: (e) => setError(refusal(e)),
  });
  const editable = !role.builtin && me.permissions.includes("user.assign_role");

  const toggle = (permission: Permission) => {
    const next = role.permissions.includes(permission)
      ? role.permissions.filter((p) => p !== permission)
      : [...role.permissions, permission];
    save.mutate(next);
  };

  return (
    <li className="rounded border border-slate-200 p-3" aria-label={role.name}>
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="font-medium">{role.name}</span>
        <span className="text-xs text-slate-500">scope: {role.scopeKind}</span>
        {role.builtin && <span className="text-xs text-slate-500">standard role, not editable</span>}
        {!role.grantable && (
          <span className="text-xs text-slate-500">above your own — you cannot grant it</span>
        )}
      </div>
      <ul className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-sm sm:grid-cols-3">
        {PERMISSIONS.map((permission) => {
          const held = me.permissions.includes(permission);
          return (
            <li key={permission}>
              <label className={held ? "" : "text-slate-400"}>
                <input
                  type="checkbox"
                  className="me-2"
                  checked={role.permissions.includes(permission)}
                  disabled={!editable || !held || save.isPending}
                  onChange={() => toggle(permission)}
                  aria-label={`${role.name}: ${permission}`}
                />
                {permission}
              </label>
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="mt-2 text-sm text-red-700">
          {error}
        </p>
      )}
    </li>
  );
}

function NewRole({ me }: { me: Me }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [scopeKind, setScopeKind] = useState<GrantScope>("team");
  const [permissions, setPermissions] = useState<Permission[]>([]);
  const [error, setError] = useState<string | null>(null);
  const create = useMutation({
    mutationFn: createRole,
    onSuccess: () => {
      setError(null);
      setName("");
      setPermissions([]);
      void queryClient.invalidateQueries({ queryKey: ["roles"] });
    },
    onError: (e) => setError(refusal(e)),
  });
  if (!me.permissions.includes("user.assign_role")) return null;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate({ name, scopeKind, permissions });
  };

  return (
    <section aria-label="new role" className="max-w-lg">
      <h2 className="text-base font-medium">New role</h2>
      <form onSubmit={submit} className="mt-2 flex flex-col gap-3 text-sm">
        <label className="flex flex-col gap-1">
          Name
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          Scope
          <select
            value={scopeKind}
            onChange={(e) => setScopeKind(e.target.value as GrantScope)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {GRANT_SCOPES.map((scope) => (
              <option key={scope} value={scope}>
                {scope}
              </option>
            ))}
          </select>
        </label>
        <fieldset>
          <legend className="mb-1">Permissions (only the ones you hold)</legend>
          <ul className="grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-3">
            {PERMISSIONS.map((permission) => {
              const held = me.permissions.includes(permission);
              return (
                <li key={permission}>
                  <label className={held ? "" : "text-slate-400"}>
                    <input
                      type="checkbox"
                      className="me-2"
                      disabled={!held}
                      checked={permissions.includes(permission)}
                      onChange={() =>
                        setPermissions((current) =>
                          current.includes(permission)
                            ? current.filter((p) => p !== permission)
                            : [...current, permission],
                        )
                      }
                      aria-label={`new role: ${permission}`}
                    />
                    {permission}
                  </label>
                </li>
              );
            })}
          </ul>
        </fieldset>
        {error && (
          <p role="alert" className="text-red-700">
            {error}
          </p>
        )}
        <button
          type="submit"
          disabled={create.isPending || name.trim() === ""}
          className="self-start rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50"
        >
          Create role
        </button>
      </form>
    </section>
  );
}
