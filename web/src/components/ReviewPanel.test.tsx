/** What the review panel says, and the three things it must never say.
 *
 * The decisions and the scoping are the database's and are guarded there
 * (`backend/tests/test_review_status.py`). What a browser can check is the
 * wording on top of them, and all three of these are the kind that gets
 * believed:
 *
 * 1. **"Nothing flagged" is not "checked and clean."** A rule the server
 *    could not evaluate is shown apart, in those words, and never folded into
 *    the violation count.
 * 2. **A project with no rules says so**, rather than borrowing the sentence
 *    that means every rule passed.
 * 3. **Work cannot be sent back without a reason**, and the control says so
 *    before somebody finds out by being refused.
 */

import { cleanup, fireEvent, screen, within } from "@testing-library/react";
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

const SUBMISSION_ID = "01SUB";

const REVIEWER: Me = {
  ...SIGNED_IN_AS_ADMIN,
  userId: "01USRSUP",
  username: "sup",
  displayName: "Sup",
  scopeKind: "team" as const,
  permissions: ["submission.view", "submission.review"],
  teamIds: ["01TEAM"],
};

const WATCHER: Me = { ...REVIEWER, permissions: ["submission.view"] };

function flag(extra: Record<string, unknown> = {}) {
  return {
    id: "01FLAG",
    ruleId: "01RULE",
    ruleName: "age in range",
    severity: "warning",
    outcome: "violation",
    detail: { reason: "failed" },
    path: "age",
    createdAt: "2026-09-10T08:00:00Z",
    resolvedAt: null,
    ...extra,
  };
}

function serve(
  me: Me,
  quality: Record<string, unknown>,
  rules: unknown[] = [{ id: "01RULE" }],
) {
  return (url: string): unknown => {
    if (url.startsWith("/health")) return { status: "ok", environment: "test" };
    if (url === "/api/v1/auth/me") return me;
    if (url.startsWith("/api/v1/quality/rules")) return { rules };
    if (url.endsWith("/quality")) return quality;
    if (url.startsWith(`/api/v1/submissions/${SUBMISSION_ID}`)) {
      return {
        id: SUBMISSION_ID,
        projectId: "01PROJ",
        formId: "hh",
        formTitle: "Household",
        formVersion: 1,
        status: "finalized",
        originDeviceId: "dev-a",
        createdBy: "01USRENUM",
        startedAt: null,
        finalizedAt: "2026-09-10T08:00:00Z",
        receivedAt: "2026-09-10T08:01:00Z",
        opCount: 2,
        state: { data: { age: 900 }, computedAt: "2026-09-10T08:01:00Z" },
        ops: [],
        opsTruncated: false,
      };
    }
    return undefined;
  };
}

const CLEAN = { flags: [], unevaluated: [], reviews: [] };

describe("a rule that could not run is not a rule that passed", () => {
  it("shows unevaluated rules apart, and says nothing has been checked", async () => {
    escapes = watchForEscapes(
      serve(REVIEWER, {
        flags: [],
        unevaluated: [
          flag({
            id: "01UNEVAL",
            outcome: "not_evaluated",
            detail: { reason: "encrypted", paths: ["age"] },
          }),
        ],
        reviews: [],
      }),
    );
    renderAt(`/submissions/${SUBMISSION_ID}`);

    expect(await screen.findByText("1 rule could not be checked")).toBeInTheDocument();
    expect(
      screen.getByText(/These did not pass and did not fail/),
    ).toBeInTheDocument();
    // And the headline does not read as a clean bill.
    expect(
      screen.getByText(/Nothing was flagged — but see below/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Every rule ran and none of them found anything."),
    ).not.toBeInTheDocument();
  });

  it("says why a rule could not run, in words", async () => {
    escapes = watchForEscapes(
      serve(REVIEWER, {
        flags: [],
        unevaluated: [
          flag({
            id: "01UNEVAL",
            outcome: "not_evaluated",
            detail: { reason: "encrypted", paths: ["age"] },
          }),
        ],
        reviews: [],
      }),
    );
    renderAt(`/submissions/${SUBMISSION_ID}`);

    expect(
      await screen.findByText(/the answer is encrypted and this server holds no key/),
    ).toBeInTheDocument();
  });

  it("says every rule ran only when every rule ran", async () => {
    escapes = watchForEscapes(serve(REVIEWER, CLEAN));
    renderAt(`/submissions/${SUBMISSION_ID}`);

    expect(
      await screen.findByText("Every rule ran and none of them found anything."),
    ).toBeInTheDocument();
  });

  it("a project with no rules says so rather than borrowing that sentence", async () => {
    escapes = watchForEscapes(serve(REVIEWER, CLEAN, []));
    renderAt(`/submissions/${SUBMISSION_ID}`);

    expect(
      await screen.findByText(
        "This project has no quality rules, so nothing has been checked.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Every rule ran and none of them found anything."),
    ).not.toBeInTheDocument();
  });
});

describe("the decision", () => {
  it("will not send work back without a reason, and says why it is needed", async () => {
    escapes = watchForEscapes(serve(REVIEWER, { ...CLEAN, flags: [flag()] }));
    renderAt(`/submissions/${SUBMISSION_ID}`);

    await screen.findByText("Quality and review");
    fireEvent.change(screen.getByRole("combobox", { name: /Decision/ }), {
      target: { value: "correction_required" },
    });

    expect(
      screen.getByText(/This is what the enumerator reads on the handset/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Record decision" })).toBeDisabled();

    fireEvent.change(screen.getByRole("textbox", { name: /What needs correcting/ }), {
      target: { value: "The age is wrong" },
    });
    expect(screen.getByRole("button", { name: "Record decision" })).toBeEnabled();
  });

  it("offers no decision to somebody who may only look", async () => {
    escapes = watchForEscapes(serve(WATCHER, { ...CLEAN, flags: [flag()] }));
    renderAt(`/submissions/${SUBMISSION_ID}`);

    expect(
      await screen.findByText(/You can see this submission but not decide on it/),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Record decision" }),
    ).not.toBeInTheDocument();
  });

  it("shows a decision that has been made, with its reason", async () => {
    escapes = watchForEscapes(
      serve(REVIEWER, {
        flags: [],
        unevaluated: [],
        reviews: [
          {
            id: "01REV",
            decision: "correction_required",
            comment: "The age is wrong — check the card.",
            reviewer: "Sup",
            createdAt: "2026-09-10T09:00:00Z",
          },
        ],
      }),
    );
    renderAt(`/submissions/${SUBMISSION_ID}`);

    const decisions = await screen.findByText("Decisions");
    const list = decisions.parentElement as HTMLElement;
    expect(within(list).getByText("Sent back for correction")).toBeInTheDocument();
    expect(
      within(list).getByText("The age is wrong — check the card."),
    ).toBeInTheDocument();
  });
});
