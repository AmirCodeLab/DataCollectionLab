/** People: who is in the organisation, who is waiting, and what to do about it.
 *
 * Pilot scope §3.2–§3.4. The list is the database's answer on the asker's
 * principal — a supervisor's page is their team — and every button here is a
 * courtesy: the permission that shows it is the permission the policy reads,
 * so a button that appears is a button that works, and one the database
 * would refuse does not appear.
 *
 * The approval queue is where §3.3 becomes visible. A person waiting is
 * listed first, and what they read as depends on who is looking: to an
 * approver, someone to approve; to the supervisor who created them, someone
 * waiting on a programme manager or an administrator — not a login that
 * fails for no reason they can see.
 */

import { useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ApiError } from "@/api/client";
import {
  approvePerson,
  createPerson,
  deactivatePerson,
  meQuery,
  peopleQuery,
  projectListQuery,
  reactivatePerson,
  rolesQuery,
  teamsQuery,
} from "@/api/queries";
import type { Me, Person, Role, Team } from "@/api/types";
import { may } from "@/lib/permissions";

function refusal(error: unknown): string {
  if (error instanceof ApiError) {
    const detail = error.detail as { reason?: string; message?: string } | string;
    if (typeof detail === "object" && detail?.message) return detail.message;
    return error.message;
  }
  return "Something went wrong.";
}

function when(iso: string | null): string {
  return iso ? iso.slice(0, 16).replace("T", " ") : "";
}

/** How a waiting person reads to this viewer. */
function Waiting({ person, me }: { person: Person; me: Me }) {
  if (may(me, "user.approve")) {
    return (
      <span className="text-amber-800">
        Waiting for your approval — created by {person.createdByName ?? "someone"} on{" "}
        {when(person.createdAt)}
      </span>
    );
  }
  const mine = person.createdBy === me.userId;
  return (
    <span className="text-amber-800">
      {mine ? "Your person is" : "This person is"} waiting for approval by a programme manager
      or an administrator, since {when(person.createdAt)}. They cannot sign in until then, but
      they can be placed in a team and assigned sample now.
    </span>
  );
}

export function PeoplePage() {
  const me = useQuery(meQuery());
  const people = useQuery(peopleQuery());
  const roles = useQuery(rolesQuery());
  const projects = useQuery(projectListQuery());
  const queryClient = useQueryClient();
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ["people"] });
  };

  const approve = useMutation({ mutationFn: approvePerson, onSuccess: refresh });
  const deactivate = useMutation({ mutationFn: deactivatePerson, onSuccess: refresh });
  const reactivate = useMutation({ mutationFn: reactivatePerson, onSuccess: refresh });
  const [actionError, setActionError] = useState<string | null>(null);
  const act = (mutation: { mutateAsync: (id: string) => Promise<unknown> }, id: string) => {
    setActionError(null);
    mutation.mutateAsync(id).catch((error: unknown) => setActionError(refusal(error)));
  };

  if (!me.data) return null;
  if (people.isPending) return <p className="text-sm text-slate-500">Loading people…</p>;
  if (people.isError) return <p className="text-sm text-red-700">{refusal(people.error)}</p>;

  const list = people.data.people;
  const waiting = list.filter((p) => p.membershipStatus === "pending_approval");
  const canApprove = may(me.data, "user.approve");
  const canDeactivate = may(me.data, "user.deactivate");

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="waiting for approval">
        <h1 className="text-xl font-semibold">People</h1>
        {waiting.length > 0 && (
          <div className="mt-3 rounded border border-amber-300 bg-amber-50 p-3">
            <h2 className="text-sm font-medium text-amber-900">
              {waiting.length === 1 ? "One person is" : `${waiting.length} people are`} waiting
              for approval
            </h2>
            <ul className="mt-2 flex flex-col gap-2 text-sm">
              {waiting.map((person) => (
                <li key={person.id} className="flex flex-wrap items-baseline gap-x-3">
                  <span className="font-medium">{person.displayName}</span>
                  <span className="text-slate-600">{person.username}</span>
                  <Waiting person={person} me={me.data} />
                  {canApprove && (
                    <button
                      type="button"
                      onClick={() => act(approve, person.id)}
                      className="rounded bg-slate-900 px-2 py-0.5 text-xs text-white"
                    >
                      Approve
                    </button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        {actionError && (
          <p role="alert" className="mt-2 text-sm text-red-700">
            {actionError}
          </p>
        )}
      </section>

      <section aria-label="everyone">
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500">
            <tr>
              <th className="py-1 pe-3 font-medium">Name</th>
              <th className="py-1 pe-3 font-medium">Username</th>
              <th className="py-1 pe-3 font-medium">Status</th>
              <th className="py-1 pe-3 font-medium">Roles</th>
              <th className="py-1 pe-3 font-medium">Team</th>
              <th className="py-1 font-medium"></th>
            </tr>
          </thead>
          <tbody>
            {list.map((person) => (
              <tr key={person.id} className="border-t border-slate-100">
                <td className="py-1 pe-3">{person.displayName}</td>
                <td className="py-1 pe-3 text-slate-600">{person.username}</td>
                <td className="py-1 pe-3">
                  <Status person={person} />
                </td>
                <td className="py-1 pe-3">
                  {person.grants.map((g) => g.roleName).join(", ") || (
                    <span className="text-slate-400">none</span>
                  )}
                </td>
                <td className="py-1 pe-3">
                  {person.teams
                    .map((t) => t.teamName)
                    .filter(Boolean)
                    .join(", ")}
                </td>
                <td className="py-1 text-end">
                  {canDeactivate && person.membershipStatus === "active" && (
                    <button
                      type="button"
                      onClick={() => act(deactivate, person.id)}
                      className="text-xs underline hover:text-red-700"
                    >
                      Deactivate
                    </button>
                  )}
                  {canApprove && person.membershipStatus === "deactivated" && (
                    <button
                      type="button"
                      onClick={() => act(reactivate, person.id)}
                      className="text-xs underline"
                    >
                      Reactivate
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      {may(me.data, "user.create") && roles.data && (
        <AddPerson
          me={me.data}
          roles={roles.data.roles.filter((r) => r.grantable)}
          projectId={projects.data?.projects[0]?.id ?? ""}
          onCreated={refresh}
        />
      )}
    </div>
  );
}

function Status({ person }: { person: Person }) {
  switch (person.membershipStatus) {
    case "active":
      return <span className="text-green-700">Active</span>;
    case "pending_approval":
      return <span className="text-amber-800">Waiting for approval</span>;
    case "deactivated":
      return <span className="text-slate-500">Deactivated {when(person.deactivatedAt)}</span>;
  }
}

/** Create a person with one role in one scope. Whether they land active or
 *  waiting is the database's decision from the creator's permissions; the
 *  response says which, and this form repeats it. */
function AddPerson({
  me,
  roles,
  projectId,
  onCreated,
}: {
  me: Me;
  roles: Role[];
  projectId: string;
  onCreated: () => void;
}) {
  const teams = useQuery(teamsQuery(projectId));
  const [displayName, setDisplayName] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [roleId, setRoleId] = useState(roles[0]?.id ?? "");
  // A supervisor's own team, pre-filled: an enumerator they create lands there (§3.2).
  const [teamId, setTeamId] = useState(me.teamIds[0] ?? "");
  const [outcome, setOutcome] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const role = roles.find((r) => r.id === roleId);
  const create = useMutation({
    mutationFn: createPerson,
    onSuccess: (person) => {
      setOutcome(
        person.membershipStatus === "pending_approval"
          ? `${person.displayName} is waiting for approval by a programme manager or an administrator.`
          : `${person.displayName} is active and can sign in now.`,
      );
      setError(null);
      setDisplayName("");
      setUsername("");
      setPassword("");
      onCreated();
    },
    onError: (e) => {
      setOutcome(null);
      setError(refusal(e));
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!role) return;
    create.mutate({
      displayName,
      username,
      password,
      roleId,
      projectId: role.scopeKind === "project" ? projectId : undefined,
      teamId: role.scopeKind === "team" ? teamId || undefined : undefined,
      membershipKind: "permanent",
    });
  };

  const teamOptions: Team[] = (teams.data?.teams ?? []).filter(
    (t) => me.scopeKind === "organization" || me.scopeKind === "project" || me.teamIds.includes(t.id),
  );

  return (
    <section aria-label="add a person" className="max-w-md">
      <h2 className="text-base font-medium">Add a person</h2>
      <form onSubmit={submit} className="mt-2 flex flex-col gap-3 text-sm">
        <label className="flex flex-col gap-1">
          Name
          <input
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          Username
          <input
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          Initial password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1">
          Role
          <select
            value={roleId}
            onChange={(e) => setRoleId(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          >
            {roles.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        {role?.scopeKind === "team" && (
          <label className="flex flex-col gap-1">
            Team
            <select
              value={teamId}
              onChange={(e) => setTeamId(e.target.value)}
              className="rounded border border-slate-300 px-2 py-1"
            >
              <option value="">—</option>
              {teamOptions.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </label>
        )}
        {!may(me, "user.approve") && (
          <p className="text-xs text-slate-600">
            People you add wait for approval by a programme manager or an administrator
            before they can sign in.
          </p>
        )}
        {error && (
          <p role="alert" className="text-red-700">
            {error}
          </p>
        )}
        {outcome && <p className="text-green-800">{outcome}</p>}
        <button
          type="submit"
          disabled={create.isPending || !role || displayName === "" || username === "" || password.length < 8}
          className="self-start rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50"
        >
          Add
        </button>
      </form>
    </section>
  );
}
