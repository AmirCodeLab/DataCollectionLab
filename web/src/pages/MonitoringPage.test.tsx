/** What the monitoring screen says, and the two things it must never say.
 *
 * The figures themselves are the database's and are guarded there
 * (`backend/tests/test_monitoring_scope.py`): a supervisor's count equals
 * their list, is strictly less than the organisation's, and matches an
 * expected subset. Nothing in a browser can check that.
 *
 * What a browser can check is the two claims this page makes on top of the
 * numbers, and both are the kind that gets believed:
 *
 * 1. **A zero is only shown where a non-zero was possible.** The server sends
 *    `flagsOutstanding: null` while no rule can raise one, and a card reading
 *    "0 flags outstanding" would be an empty table wearing a measurement's
 *    clothes.
 * 2. **A count this server did not compute carries the time it was reported.**
 *    "3 waiting" and "3 waiting, as of 08:14" are different claims, and it is
 *    the second one a supervisor can act on at four in the afternoon.
 */

import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Me } from "@/api/types";
import {
  SIGNED_IN_AS_ADMIN,
  renderAt,
  watchForEscapes,
  type Escapes,
} from "@/test/harness";

let escapes: Escapes;

afterEach(() => {
  cleanup();
  escapes.restore();
});

const PROJECT_ID = "01PROJ";

const SUPERVISOR: Me = {
  ...SIGNED_IN_AS_ADMIN,
  userId: "01USRSUPA",
  username: "sup-a",
  displayName: "Sup A",
  scopeKind: "team" as const,
  permissions: ["submission.view", "sample.assign"],
  teamIds: ["01TEAMA"],
};

function overview(extra: Record<string, unknown> = {}) {
  return {
    scopeKind: "team",
    scopeLabel: "your team",
    casesAssigned: 40,
    casesCovered: 12,
    submissions: 14,
    uncasedSubmissions: 2,
    devices: 3,
    flagsOutstanding: null,
    perDay: [
      { date: "2026-09-09", count: 5 },
      { date: "2026-09-10", count: 7 },
    ],
    ...extra,
  };
}

function device(extra: Record<string, unknown> = {}) {
  return {
    deviceId: "dev-ca",
    person: "Enum A",
    platform: "android",
    appVersion: "0.4.1",
    lastSyncAt: "2026-09-10T08:14:00Z",
    reportedPendingOps: 3,
    reportedAt: "2026-09-10T08:14:00Z",
    ...extra,
  };
}

function serve(me: Me, body: Record<string, unknown> = {}) {
  const data = {
    overview: overview(),
    enumerators: { enumerators: [] },
    areas: { column: null, areas: [] },
    devices: { devices: [device()] },
    ...body,
  };
  return (url: string): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/auth/me") return me;
    if (url === "/api/v1/projects") {
      return {
        projects: [
          {
            id: PROJECT_ID,
            name: "Village census",
            slug: "village",
            securityMode: "standard",
            activeKeyCount: 0,
            createdAt: "2026-08-01T00:00:00Z",
            archivedAt: null,
          },
        ],
      };
    }
    if (url.startsWith("/api/v1/monitoring/overview")) return data.overview;
    if (url.startsWith("/api/v1/monitoring/enumerators")) return data.enumerators;
    if (url.startsWith("/api/v1/monitoring/areas")) return data.areas;
    if (url.startsWith("/api/v1/monitoring/devices")) return data.devices;
    return undefined;
  };
}

describe("whose figures these are", () => {
  it("says the scope beside the numbers, so a zero is not read as none anywhere", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(
      await screen.findByText(/Everything on this page is your team/),
    ).toBeInTheDocument();
    expect(screen.getByText(/A zero here means none of yours, not none anywhere/))
      .toBeInTheDocument();
    expect(screen.getByText("Cases assigned in your team")).toBeInTheDocument();
  });

  it("counts work with no case apart from progress", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(await screen.findByText("Not against a case")).toBeInTheDocument();
    expect(screen.getByText("counted apart from progress")).toBeInTheDocument();
  });
});

describe("a zero only where a non-zero was possible", () => {
  it("renders no flags card while nothing can raise a flag", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    // Wait for something only the loaded overview renders. "Submissions" was
    // the first choice and it is also the nav link, so the query ran before
    // the figures existed and the assertion passed whatever the page did —
    // found by breaking the page and watching this test stay green.
    await screen.findByText("Cases assigned in your team");
    // Null is not zero: until item 6 gives quality rules a writer, there is
    // no measurement to show, and "0 outstanding" would be believed.
    expect(screen.queryByText("Flags outstanding")).not.toBeInTheDocument();
  });

  it("renders the card once a rule exists, even when the count is zero", async () => {
    escapes = watchForEscapes(
      serve(SUPERVISOR, { overview: overview({ flagsOutstanding: 0 }) }),
    );
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(await screen.findByText("Flags outstanding")).toBeInTheDocument();
  });
});

describe("the device panel", () => {
  it("shows the reported backlog with the time it was reported, in the row", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    // Not in a tooltip, not on hover: in the cell, beside the number.
    expect(
      await screen.findByText("3 waiting, as of 2026-09-10 08:14"),
    ).toBeInTheDocument();
  });

  it("says nothing waiting, with its time, rather than a bare zero", async () => {
    escapes = watchForEscapes(
      serve(SUPERVISOR, {
        devices: { devices: [device({ reportedPendingOps: 0 })] },
      }),
    );
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(
      await screen.findByText("nothing waiting, as of 2026-09-10 08:14"),
    ).toBeInTheDocument();
  });

  it("says a device has not reported rather than showing a count of zero", async () => {
    escapes = watchForEscapes(
      serve(SUPERVISOR, {
        devices: {
          devices: [device({ reportedPendingOps: null, reportedAt: null })],
        },
      }),
    );
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(await screen.findByText("not reported yet")).toBeInTheDocument();
    expect(screen.queryByText(/waiting/)).not.toBeInTheDocument();
  });

  it("names a handset nobody has signed in on rather than leaving the cell blank", async () => {
    escapes = watchForEscapes(
      serve(SIGNED_IN_AS_ADMIN, {
        devices: { devices: [device({ person: null, deviceId: "dev-unclaimed" })] },
      }),
    );
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    const row = (await screen.findByText("dev-unclaimed")).closest("tr");
    expect(row).not.toBeNull();
    expect(within(row as HTMLElement).getByText("nobody yet")).toBeInTheDocument();
  });
});

describe("finished per day", () => {
  it("says which day it is counting", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(
      await screen.findByText(
        /By the day the enumerator finished, not the day it reached the server/,
      ),
    ).toBeInTheDocument();
  });

  it("says nothing finished in your scope rather than showing an empty chart", async () => {
    escapes = watchForEscapes(serve(SUPERVISOR, { overview: overview({ perDay: [] }) }));
    renderAt(`/projects/${PROJECT_ID}/monitoring`);

    expect(
      await screen.findByText("Nothing finished in your team in the last two weeks."),
    ).toBeInTheDocument();
  });
});
