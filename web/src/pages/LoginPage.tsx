/** Sign in. One form, one POST, and nothing kept in the page.
 *
 * The session is a cookie the server sets HttpOnly (proposal §3.2): this page
 * never sees a token, so it has nothing to store and nothing to leak. What it
 * keeps is `Me` — who this is and which permissions they hold — in the query
 * cache, which is what every other screen reads to decide what to render.
 */

import { useState, type FormEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "@tanstack/react-router";

import { ApiError } from "@/api/client";
import { login, ME_QUERY_KEY } from "@/api/queries";
import type { LoginError } from "@/api/types";

/** What a refusal reads as. The reason is the contract; the text is ours. */
function describe(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Try again.";
  const detail = error.detail as Partial<LoginError> | string | undefined;
  const reason = typeof detail === "object" && detail ? detail.reason : undefined;
  switch (reason) {
    case "invalid_credentials":
      return "Wrong username or password.";
    case "pending_approval":
      return "This account is waiting for approval by an administrator.";
    case "deactivated":
      return "This account has been deactivated.";
    case "no_membership":
      return "This account is not a member of the organisation.";
    default:
      return error.status === 0 ? "The server could not be reached." : error.message;
  }
}

export function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  const signIn = useMutation({
    mutationFn: () => login({ username, password, kind: "console" }),
    onSuccess: (me) => {
      queryClient.setQueryData(ME_QUERY_KEY, me);
      void navigate({ to: "/submissions", search: {} });
    },
  });

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (username.trim() === "" || password === "") return;
    signIn.mutate();
  };

  return (
    <div className="mx-auto mt-16 max-w-sm">
      <h1 className="mb-6 text-xl font-semibold">Sign in</h1>
      <form onSubmit={submit} className="flex flex-col gap-4" aria-label="sign in">
        <label className="flex flex-col gap-1 text-sm">
          Username
          <input
            name="username"
            autoComplete="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Password
          <input
            name="password"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="rounded border border-slate-300 px-2 py-1"
          />
        </label>
        {signIn.isError && (
          <p role="alert" className="text-sm text-red-700">
            {describe(signIn.error)}
          </p>
        )}
        <button
          type="submit"
          disabled={signIn.isPending}
          className="rounded bg-slate-900 px-3 py-1.5 text-white disabled:opacity-50"
        >
          {signIn.isPending ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
