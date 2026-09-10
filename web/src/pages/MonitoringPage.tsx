/** The screen a supervisor lives in during fieldwork (item 5).
 *
 * Every number here is a count the database made over the same rows this
 * person may list, so a figure and the list it links to are one answer. That
 * is why each one is a link: the way somebody checks a total they doubt is to
 * look at what it counted.
 *
 * Two things on this page are decisions rather than layout.
 *
 * **Whose figures these are is written beside them.** A supervisor's are their
 * team's. "0" on a scoped screen means "none of yours", and a screen that does
 * not say so invites it to be read as "none anywhere" — which is the failure
 * that makes a monitoring screen worse than no screen, because it is trusted.
 *
 * **A count the server did not compute travels with the time it was reported.**
 * The device panel's backlog is the handset's own word from its last sync.
 * "3 pending" and "3 pending, as of 08:14" are different claims, and it is the
 * second one a supervisor can act on at four in the afternoon.
 */

import { Link, getRouteApi } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import {
  meQuery,
  monitoringAreasQuery,
  monitoringDevicesQuery,
  monitoringEnumeratorsQuery,
  monitoringOverviewQuery,
  projectListQuery,
} from "@/api/queries";
import type { DeviceStatus, Overview } from "@/api/types";
import { Td, Th } from "@/components/Table";

const route = getRouteApi("/projects/$projectId/monitoring");

/** "12 of 40" with the share, or a plain dash when there is nothing to divide. */
function share(part: number, whole: number): string {
  if (whole === 0) return "—";
  return `${Math.round((part / whole) * 100)}%`;
}

/** `2026-09-10T08:14:23Z` → `2026-09-10 08:14`. */
function when(iso: string | null): string | null {
  return iso ? iso.slice(0, 16).replace("T", " ") : null;
}

export function MonitoringPage() {
  const { projectId } = route.useParams();
  const me = useQuery(meQuery());
  const projects = useQuery(projectListQuery());
  const overview = useQuery(monitoringOverviewQuery(projectId));
  const enumerators = useQuery(monitoringEnumeratorsQuery(projectId));
  const areas = useQuery(monitoringAreasQuery(projectId));
  const devices = useQuery(monitoringDevicesQuery(projectId));

  if (!me.data) return null;
  const project = projects.data?.projects.find((p) => p.id === projectId);

  return (
    <section>
      <p className="text-sm">
        <Link to="/projects" className="text-blue-700 hover:underline">
          Projects
        </Link>
        {project && <> › {project.name}</>}
      </p>
      <h1 className="mt-1 text-xl font-semibold">Monitoring</h1>

      {overview.isError && (
        <p role="alert" className="mt-4 text-red-700">
          Could not load these figures: {String(overview.error)}
        </p>
      )}
      {overview.data && <Figures overview={overview.data} projectId={projectId} />}

      {enumerators.data && enumerators.data.enumerators.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-medium">By enumerator</h2>
          <p className="mt-1 text-sm text-slate-600">
            Assigned is the cases they hold now. Done is the ones they have
            finished with.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[40rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-300 text-slate-600">
                  <Th>Enumerator</Th>
                  <Th>Assigned</Th>
                  <Th>Done</Th>
                  <Th>Share</Th>
                  <Th>Last sync</Th>
                </tr>
              </thead>
              <tbody>
                {enumerators.data.enumerators.map((person) => (
                  <tr key={person.userId} className="border-b border-slate-100">
                    <Td>{person.displayName}</Td>
                    <Td>{person.assigned}</Td>
                    <Td>{person.covered}</Td>
                    <Td>{share(person.covered, person.assigned)}</Td>
                    <Td className="whitespace-nowrap">
                      {when(person.lastSyncAt) ?? (
                        <span className="text-slate-400">never</span>
                      )}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {areas.data && areas.data.areas.length > 0 && (
        <div className="mt-8">
          <h2 className="text-lg font-medium">By area</h2>
          <p className="mt-1 text-sm text-slate-600">
            Grouped by <code>{areas.data.column}</code>, the first key column of
            the sample. Each row is your part of that area, not the area&apos;s
            total.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[32rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-300 text-slate-600">
                  <Th>Area</Th>
                  <Th>Assigned</Th>
                  <Th>Done</Th>
                  <Th>Share</Th>
                </tr>
              </thead>
              <tbody>
                {areas.data.areas.map((area) => (
                  <tr key={area.area} className="border-b border-slate-100">
                    <Td>{area.area}</Td>
                    <Td>{area.assigned}</Td>
                    <Td>{area.covered}</Td>
                    <Td>{share(area.covered, area.assigned)}</Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {devices.data && (
        <div className="mt-8">
          <h2 className="text-lg font-medium">Devices</h2>
          <p className="mt-1 text-sm text-slate-600">
            The handsets of people you can see. A device nobody has signed in on
            belongs to nobody and is not listed here.
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-slate-300 text-slate-600">
                  <Th>Person</Th>
                  <Th>Device</Th>
                  <Th>Last sync</Th>
                  <Th>Waiting on the device</Th>
                </tr>
              </thead>
              <tbody>
                {devices.data.devices.map((device) => (
                  <tr key={device.deviceId} className="border-b border-slate-100">
                    <Td>
                      {device.person ?? (
                        <span className="text-slate-400">nobody yet</span>
                      )}
                    </Td>
                    <Td>
                      <span className="font-mono text-xs">{device.deviceId}</span>
                      <div className="text-xs text-slate-500">
                        {device.platform}
                        {device.appVersion ? ` · ${device.appVersion}` : ""}
                      </div>
                    </Td>
                    <Td className="whitespace-nowrap">
                      {when(device.lastSyncAt) ?? (
                        <span className="text-slate-400">never</span>
                      )}
                    </Td>
                    <Td>
                      <Backlog device={device} />
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
            {devices.data.devices.length === 0 && (
              <p className="py-6 text-slate-500">No devices in your scope.</p>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

/**
 * What the handset last said was queued on it, and when it said so.
 *
 * The two are rendered together or not at all. This server does not know what
 * is in a device's outbox — it knows what it has accepted — so the figure is a
 * report with a timestamp, and stripping the timestamp turns it into a claim
 * about now.
 */
function Backlog({ device }: { device: DeviceStatus }) {
  if (device.reportedPendingOps === null || device.reportedAt === null) {
    return <span className="text-slate-400">not reported yet</span>;
  }
  const count = device.reportedPendingOps;
  return (
    <span className={count > 0 ? "text-amber-700" : undefined}>
      {count === 0 ? "nothing waiting" : `${count} waiting`}, as of{" "}
      {when(device.reportedAt)}
    </span>
  );
}

function Figures({ overview, projectId }: { overview: Overview; projectId: string }) {
  const busiest = Math.max(1, ...overview.perDay.map((d) => d.count));
  return (
    <>
      <p className="mt-1 text-sm text-slate-600">
        Everything on this page is {overview.scopeLabel}. A zero here means none
        of yours, not none anywhere.
      </p>

      <div className="mt-4 flex flex-wrap gap-3">
        <Figure label={`Cases assigned in ${overview.scopeLabel}`} value={overview.casesAssigned}>
          <Link
            to="/projects/$projectId/sample"
            params={{ projectId }}
            className="text-blue-700 hover:underline"
          >
            the cases
          </Link>
        </Figure>
        <Figure
          label="Finished"
          value={overview.casesCovered}
          note={share(overview.casesCovered, overview.casesAssigned)}
        />
        <Figure label="Submissions" value={overview.submissions}>
          <Link to="/submissions" className="text-blue-700 hover:underline">
            the submissions
          </Link>
        </Figure>
        <Figure
          label="Not against a case"
          value={overview.uncasedSubmissions}
          note="counted apart from progress"
        />
        <Figure label="Devices" value={overview.devices} />
        {/* No card for quality flags while nothing can raise one. The server
            answers null rather than 0 for exactly this reason: a zero here
            would be an empty table rendered as a measurement, which is the
            version people trust because it looks like data (item 5, A7). */}
        {overview.flagsOutstanding !== null && (
          <Figure label="Flags outstanding" value={overview.flagsOutstanding} />
        )}
      </div>

      <div className="mt-8">
        <h2 className="text-lg font-medium">Finished per day</h2>
        <p className="mt-1 text-sm text-slate-600">
          By the day the enumerator finished, not the day it reached the server.
          A handset offline for three days did not stop working.
        </p>
        {overview.perDay.length === 0 ? (
          <p className="mt-2 text-slate-500">
            Nothing finished in {overview.scopeLabel} in the last two weeks.
          </p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1">
            {overview.perDay.map((day) => (
              <li key={day.date} className="flex items-center gap-2 text-sm">
                <span className="w-24 font-mono text-xs text-slate-500">{day.date}</span>
                <span
                  className="inline-block h-3 rounded bg-slate-800"
                  style={{ width: `${(day.count / busiest) * 12}rem` }}
                />
                <span>{day.count}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}

function Figure({
  label,
  value,
  note,
  children,
}: {
  label: string;
  value: number;
  note?: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="min-w-[10rem] rounded border border-slate-200 p-3">
      <div className="text-2xl font-semibold">{value}</div>
      <div className="text-sm text-slate-600">{label}</div>
      {note && <div className="text-xs text-slate-500">{note}</div>}
      {children && <div className="mt-1 text-xs">{children}</div>}
    </div>
  );
}
