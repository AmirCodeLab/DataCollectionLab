/** Encryption keys for one project (encryption envelope §4.1, §4.3).
 *
 * The keypair is generated in this browser. The private half is downloaded and
 * never leaves the machine; only the public half is uploaded. The order below
 * is deliberate — the file is saved BEFORE the public key is registered, so a
 * failed upload costs nothing and a failed download cannot leave a project
 * wrapping submissions to a key nobody holds.
 */

import { useState } from "react";
import { Link, getRouteApi } from "@tanstack/react-router";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { addProjectKey, projectKeysQuery, projectListQuery } from "@/api/queries";
import { KEY_ROLES, type KeyRole, type SecurityMode } from "@/api/types";
import { Td, Th } from "@/components/Table";
import { formatTimestamp } from "@/lib/format";
import {
  downloadPrivateKey,
  generateProjectKeypair,
  privateKeyFileContents,
  privateKeyFilename,
} from "@/lib/projectKey";

const route = getRouteApi("/projects/$projectId/keys");

const MODE_NOTE: Record<SecurityMode, string> = {
  standard: "Nothing is encrypted end-to-end. Recipient keys are unused here.",
  field_level:
    "Values of fields marked sensitive are encrypted to these keys. Everything else stays queryable.",
  project_e2e:
    "Every operation value is encrypted to these keys. The server can read none of it.",
};

const ROLE_NOTE: Record<KeyRole, string> = {
  primary: "The day-to-day holder.",
  backup: "A second holder, so one lost laptop is not the end of the data.",
  recovery: "Cold storage — a safe, an ethics board, an escrow agent.",
};

export function ProjectKeysPage() {
  const { projectId } = route.useParams();
  const queryClient = useQueryClient();

  const projects = useQuery(projectListQuery());
  const keys = useQuery(projectKeysQuery(projectId));

  const project = projects.data?.projects.find((p) => p.id === projectId);

  const [role, setRole] = useState<KeyRole>("primary");
  const [label, setLabel] = useState("");
  const [saved, setSaved] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const generate = useMutation({
    mutationFn: async () => {
      setStatus("Generating a keypair in this browser…");
      const keypair = await generateProjectKeypair();

      // Save first. If the upload fails after this, the worst case is an
      // unused private key on someone's disk. If the upload succeeded first
      // and the download then failed, devices would start wrapping to a key
      // nobody holds — and that data would never be readable again.
      setStatus("Saving the private key…");
      downloadPrivateKey(
        privateKeyFileContents(keypair, {
          projectId,
          keyId: null,
          role,
          label,
        }),
        privateKeyFilename(project?.slug ?? projectId, role),
      );

      setStatus("Registering the public key…");
      return addProjectKey(projectId, {
        publicKey: keypair.publicKey,
        role,
        label,
      });
    },
    onSuccess: async (created) => {
      setStatus(
        `Registered ${created.keyId}. Check your downloads folder — the private ` +
          "key file is the only copy that will ever exist. This key opens only " +
          "submissions encrypted from now on: everything already collected stays " +
          "wrapped to the keys that existed when it was collected, and cannot be " +
          "re-wrapped. Keep those private keys.",
      );
      setLabel("");
      setSaved(false);
      await queryClient.invalidateQueries({ queryKey: ["project-keys", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["projects"] });
    },
    onError: () => setStatus(null),
  });

  const active = keys.data?.keys ?? [];
  const canSubmit = label.trim() !== "" && saved && !generate.isPending;

  return (
    <section className="max-w-4xl">
      <Link to="/projects" className="text-sm text-blue-700 hover:underline">
        ← All projects
      </Link>

      <h1 className="mt-2 text-xl font-semibold">
        Encryption keys{project ? ` — ${project.name}` : ""}
      </h1>
      <p className="mt-1 text-sm text-slate-600">
        <span className="font-mono text-xs">{projectId}</span>
        {keys.data && (
          <>
            {" · "}
            <code>{keys.data.securityMode}</code>{" "}
            {MODE_NOTE[keys.data.securityMode]}
          </>
        )}
      </p>

      {keys.data?.securityMode !== "standard" && active.length === 0 && (
        <p className="mt-4 rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          This project has no recipient keys, so devices cannot sync: rather
          than send answers in the clear, they hold everything on the device
          until a key exists. Generate one below.
        </p>
      )}

      <h2 className="mt-8 text-lg font-semibold">Recipients</h2>
      <p className="text-sm text-slate-600">
        Every submission&apos;s content key is wrapped once per active key at the
        moment it is collected, so any one of these private keys opens the
        submissions collected while it was registered — and no others.
      </p>

      {keys.isPending && <p className="mt-3 text-slate-500">Loading…</p>}
      {keys.isError && (
        <p className="mt-3 text-red-600">
          Could not load keys: {String(keys.error)}
        </p>
      )}
      {keys.data && active.length === 0 && (
        <p className="mt-3 text-slate-500">No keys yet.</p>
      )}
      {active.length > 0 && (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[40rem] border-collapse text-sm">
            <thead>
              <tr className="border-b border-slate-300 text-slate-600">
                <Th>Role</Th>
                <Th>Label</Th>
                <Th>Public key</Th>
                <Th>Added</Th>
                <Th>Opens</Th>
              </tr>
            </thead>
            <tbody>
              {active.map((key) => (
                <tr key={key.keyId} className="border-b border-slate-100">
                  <Td>
                    <code>{key.role}</code>
                  </Td>
                  <Td>{key.label}</Td>
                  <Td className="break-all font-mono text-xs">{key.publicKey}</Td>
                  <Td className="whitespace-nowrap text-xs">
                    {formatTimestamp(key.createdAt)}
                  </Td>
                  <Td className="whitespace-nowrap text-xs text-slate-600">
                    submissions encrypted after this
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {active.length > 0 && (
        <p className="mt-2 max-w-3xl text-xs text-slate-600">
          A key opens nothing collected before it was added. Devices wrap each
          submission&apos;s content key to the recipients that exist at that
          moment, and historical submissions are never re-wrapped — the server
          cannot re-wrap them, because it cannot open them (encryption envelope
          §8). Reading older data always needs the private keys that were
          registered then.
        </p>
      )}

      <h2 className="mt-8 text-lg font-semibold">Add a recipient</h2>

      <div className="mt-3 rounded border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900">
        <p className="font-semibold">
          The private key is generated here and downloaded to this computer. It
          is never sent to the server.
        </p>
        <p className="mt-2">
          That means nobody can reset it, reissue it or recover it — not us, not
          your administrator. If the file is lost, every submission encrypted to
          it is unreadable permanently. This is the guarantee working as
          intended, not a gap in it.
        </p>
        <p className="mt-2">
          Add a <code>backup</code> and a <code>recovery</code> key as well, held
          by different people in different places.
        </p>
        {active.length > 0 && (
          <p className="mt-2 border-t border-red-200 pt-2">
            <span className="font-semibold">
              This key cannot open submissions encrypted before now.
            </span>{" "}
            The {active.length} recipient{active.length === 1 ? "" : "s"} above
            already hold every submission collected so far, and nothing gets
            re-wrapped when a key is added — the server has no way to, since it
            cannot open them either (envelope §8). Adding a key is not a way to
            regain access to existing data, and rotating away from a key you then
            discard destroys everything encrypted to it.
          </p>
        )}
      </div>

      <form
        className="mt-4 space-y-4"
        onSubmit={(event) => {
          event.preventDefault();
          generate.mutate();
        }}
      >
        <div>
          <label className="block text-sm font-medium" htmlFor="role">
            Role
          </label>
          <select
            id="role"
            className="mt-1 rounded border border-slate-300 px-2 py-1 text-sm"
            value={role}
            onChange={(event) => setRole(event.target.value as KeyRole)}
          >
            {KEY_ROLES.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-600">{ROLE_NOTE[role]}</p>
        </div>

        <div>
          <label className="block text-sm font-medium" htmlFor="label">
            Who holds this key?
          </label>
          <input
            id="label"
            className="mt-1 w-full max-w-md rounded border border-slate-300 px-2 py-1 text-sm"
            placeholder="Programme lead — Fatima"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            maxLength={200}
          />
          <p className="mt-1 text-xs text-slate-600">
            The only thing that will identify the holder when someone needs this
            data back in two years.
          </p>
        </div>

        <label className="flex items-start gap-2 text-sm">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={saved}
            onChange={(event) => setSaved(event.target.checked)}
          />
          <span>
            I understand the private key file cannot be recovered if it is lost,
            and I will store it somewhere durable.
          </span>
        </label>

        <button
          type="submit"
          disabled={!canSubmit}
          className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:bg-slate-300"
        >
          {generate.isPending
            ? "Generating…"
            : "Generate keypair and download private key"}
        </button>
      </form>

      {status && <p className="mt-3 text-sm text-slate-700">{status}</p>}
      {generate.isError && (
        <p className="mt-3 text-sm text-red-600">
          {String(generate.error)}
          <br />
          <span className="text-slate-600">
            No key was registered. If a private key file was downloaded, delete
            it — it opens nothing.
          </span>
        </p>
      )}
    </section>
  );
}
