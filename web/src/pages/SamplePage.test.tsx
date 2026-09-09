/** The sample page renders what the database showed, and sends what the
 *  database will decide on.
 *
 * The page has no scope logic of its own: a supervisor's list is whatever
 * `/cases` answered on their principal. So the tests here are about the two
 * things the page does add — the upload's multipart request and the split's
 * bulk assignment — and about the page not inventing a control the database
 * would refuse (no upload form for someone without `sample.upload`).
 */

import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { Case, Me } from "@/api/types";
import {
  SIGNED_IN_AS_ADMIN,
  renderAt,
  reply,
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
  permissions: ["sample.assign", "submission.view"],
  teamIds: ["01TEAMA"],
};

function aCase(id: string, key: string, holder: Partial<Case["holder"]> = {}): Case {
  return {
    id,
    projectId: PROJECT_ID,
    datasetKey: "village",
    caseKey: key,
    status: "open",
    priority: 0,
    dueAt: null,
    data: { case_key: key, headName: `Head of ${key}` },
    holder: { teamId: null, teamName: null, userId: null, userName: null, assignedAt: null, ...holder },
    submissions: 0,
  };
}

const TEAM_A = {
  id: "01TEAMA",
  projectId: PROJECT_ID,
  name: "Team A",
  parentTeamId: null,
  members: [
    { userId: "01USRENUMA", displayName: "Enum A", membershipStatus: "active" as const },
    { userId: "01USRSUPA", displayName: "Sup A", membershipStatus: "active" as const },
  ],
};

interface Sent {
  assignments: string[];
  uploads: string[];
}

function serve(me: Me, cases: Case[], sent: Sent) {
  return (url: string, init?: RequestInit): unknown => {
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
    if (url.startsWith("/api/v1/teams")) return { teams: [TEAM_A] };
    if (url.startsWith("/api/v1/cases?")) return { cases };
    if (url === "/api/v1/cases/assign" && init?.method === "POST") {
      sent.assignments.push(String(init.body));
      const request = JSON.parse(String(init.body)) as { caseIds: string[]; userId?: string };
      if (request.userId === "01USRENUMB") {
        return reply(403, {
          detail: {
            reason: "outside_your_authority",
            message: "The database refused this: the person is not in the team that holds the case.",
          },
        });
      }
      return { assigned: request.caseIds.length };
    }
    if (url === `/api/v1/projects/${PROJECT_ID}/samples` && init?.method === "POST") {
      const form = init.body as FormData;
      sent.uploads.push(
        `${String(form.get("datasetKey"))} ${String(form.get("keyColumns"))} ${(form.get("file") as File).name}`,
      );
      return {
        datasetKey: "village",
        datasetVersionId: "01DSV",
        version: 1,
        rowCount: 3,
        createdVersion: true,
        keyColumns: ["settlementCode", "structureId", "hhId"],
        casesCreated: 3,
        casesReopened: 0,
        casesWithdrawn: 0,
        warnings: [],
      };
    }
    return undefined;
  };
}

describe("what is listed", () => {
  it("shows the supervisor exactly what /cases answered, with no upload form", async () => {
    const sent: Sent = { assignments: [], uploads: [] };
    const mine = [
      aCase("c1", "S3|1|1", { teamId: "01TEAMA", teamName: "Team A" }),
      aCase("c2", "S3|1|2", {
        teamId: "01TEAMA",
        teamName: "Team A",
        userId: "01USRENUMA",
        userName: "Enum A",
      }),
    ];
    escapes = watchForEscapes(serve(SUPERVISOR, mine, sent));
    renderAt(`/projects/${PROJECT_ID}/sample`);

    expect(await screen.findByText("S3|1|1")).toBeInTheDocument();
    expect(screen.getByText("S3|1|2")).toBeInTheDocument();
    expect(screen.getByText(/2 cases\. You see the cases held by your team\./)).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("Enum A")).toBeInTheDocument();
    expect(screen.queryByRole("form", { name: "upload a sample" })).not.toBeInTheDocument();
    // The list came from the one request, with the project named and nothing else.
    expect(escapes.requests.filter((r) => r.includes("/api/v1/cases?"))).toEqual([
      `GET /api/v1/cases?projectId=${PROJECT_ID} `,
    ]);
  });
});

describe("the split", () => {
  it("assigns the selected cases to one person in one request, and shows the count", async () => {
    const sent: Sent = { assignments: [], uploads: [] };
    const mine = [
      aCase("c1", "S3|1|1", { teamId: "01TEAMA", teamName: "Team A" }),
      aCase("c2", "S3|1|2", { teamId: "01TEAMA", teamName: "Team A" }),
    ];
    escapes = watchForEscapes(serve(SUPERVISOR, mine, sent));
    renderAt(`/projects/${PROJECT_ID}/sample`);
    await screen.findByText("S3|1|1");

    fireEvent.click(screen.getByRole("checkbox", { name: "select S3|1|1" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "select S3|1|2" }));
    const bar = screen.getByRole("group", { name: "assign selected cases" });
    fireEvent.change(within(bar).getByRole("combobox", { name: "holder" }), {
      target: { value: "person:01USRENUMA" },
    });
    fireEvent.click(within(bar).getByRole("button", { name: "Assign" }));

    await within(bar).findByRole("status");
    expect(within(bar).getByRole("status")).toHaveTextContent("2 cases assigned.");
    expect(sent.assignments).toEqual([
      JSON.stringify({ caseIds: ["c1", "c2"], teamId: null, userId: "01USRENUMA" }),
    ]);
  });

  it("shows the database's refusal by its message, and keeps the selection", async () => {
    const sent: Sent = { assignments: [], uploads: [] };
    const teams = { ...TEAM_A, members: [...TEAM_A.members, { userId: "01USRENUMB", displayName: "Enum B", membershipStatus: "active" as const }] };
    const handler = serve(SUPERVISOR, [aCase("c1", "S3|1|1", { teamId: "01TEAMA", teamName: "Team A" })], sent);
    escapes = watchForEscapes((url, init) =>
      url.startsWith("/api/v1/teams") ? { teams: [teams] } : handler(url, init),
    );
    renderAt(`/projects/${PROJECT_ID}/sample`);
    await screen.findByText("S3|1|1");

    fireEvent.click(screen.getByRole("checkbox", { name: "select S3|1|1" }));
    const bar = screen.getByRole("group", { name: "assign selected cases" });
    fireEvent.change(within(bar).getByRole("combobox", { name: "holder" }), {
      target: { value: "person:01USRENUMB" },
    });
    fireEvent.click(within(bar).getByRole("button", { name: "Assign" }));

    await within(bar).findByRole("alert");
    expect(within(bar).getByRole("alert")).toHaveTextContent(/not in the team that holds the case/);
    expect(screen.getByRole("checkbox", { name: "select S3|1|1" })).toBeChecked();
  });
});

describe("the upload", () => {
  it("sends the file, the dataset key and the key columns as one multipart request", async () => {
    const sent: Sent = { assignments: [], uploads: [] };
    escapes = watchForEscapes(serve(SIGNED_IN_AS_ADMIN, [], sent));
    renderAt(`/projects/${PROJECT_ID}/sample`);
    const form = await screen.findByRole("form", { name: "upload a sample" });

    const file = new File(["settlementCode,structureId,hhId\nS3,1,1\n"], "sample.csv", {
      type: "text/csv",
    });
    fireEvent.change(within(form).getByLabelText("File"), { target: { files: [file] } });
    fireEvent.change(within(form).getByLabelText("Dataset key"), { target: { value: "village" } });
    fireEvent.change(within(form).getByLabelText("Key columns, in order"), {
      target: { value: "settlementCode, structureId ,hhId" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Upload" }));

    await waitFor(() => expect(sent.uploads).toHaveLength(1));
    expect(sent.uploads).toEqual(["village settlementCode,structureId,hhId sample.csv"]);
    expect(within(form).getByRole("status")).toHaveTextContent(
      "Version 1 of village: 3 rows; 3 cases created, 0 reopened, 0 withdrawn.",
    );
  });
});
