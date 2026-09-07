/** A hand-built engine for tests: returns whatever states the test hands it
 *  and records what it was asked. Never computes anything, because the point
 *  of these tests is that the pane does not either. */

import type {
  EngineModule,
  PreviewState,
  TraceNode,
} from "@/builder/engine/facade";

export const emptyState: PreviewState = {
  screen: {
    index: 0,
    kind: "questions",
    groupId: null,
    sectionId: null,
    repeatId: null,
    title: null,
  },
  inside: null,
  progress: [1, 1],
  hasNext: false,
  hasPrevious: false,
  questions: [],
  roster: null,
  canFinalize: true,
  blockers: [],
  values: {},
  relevant: {},
  valid: {},
};

export const questionsState: PreviewState = {
  ...emptyState,
  screen: {
    index: 2,
    kind: "questions",
    groupId: "page",
    sectionId: null,
    repeatId: null,
    title: "Consent",
  },
  progress: [3, 8],
  hasNext: true,
  hasPrevious: true,
  questions: [
    {
      path: "consent",
      id: "consent",
      dataType: "select_one",
      label: "Consent given?",
      hint: null,
      required: true,
      readOnly: false,
      relevant: true,
      value: null,
      valid: false,
      errors: [{ kind: "required", severity: "error", message: null }],
      choices: [
        { value: "yes", label: "Yes" },
        { value: "no", label: "No" },
      ],
    },
    {
      path: "age",
      id: "age",
      dataType: "integer",
      label: "Age",
      hint: "completed years",
      required: false,
      readOnly: false,
      relevant: true,
      value: 41,
      valid: true,
      errors: [],
      choices: [],
    },
    {
      path: "hidden",
      id: "hidden",
      dataType: "text",
      label: "Never shown here",
      hint: null,
      required: false,
      readOnly: false,
      relevant: false,
      value: null,
      valid: true,
      errors: [],
      choices: [],
    },
  ],
  values: { consent: null, age: 41, hidden: null },
  relevant: { consent: true, age: true, hidden: false },
  valid: { consent: false, age: true, hidden: true },
};

export const rosterState: PreviewState = {
  ...emptyState,
  screen: {
    index: 4,
    kind: "repeat",
    groupId: null,
    sectionId: "members",
    repeatId: "members",
    title: null,
  },
  progress: [5, 8],
  hasNext: true,
  hasPrevious: true,
  roster: {
    repeatId: "members",
    title: "Household members",
    rows: [
      { instanceId: "i1", label: "Mother", canDelete: false },
      { instanceId: "i2", label: "Father", canDelete: false },
    ],
    canAdd: true,
    addLabel: "Add a member",
  },
};

export const insideState: PreviewState = {
  ...rosterState,
  inside: {
    repeatId: "members",
    instanceId: "i2",
    rowLabel: "Father",
    within: [1, 2],
    across: [2, 2],
  },
  roster: null,
  questions: [
    {
      path: "members[i2].name",
      id: "name",
      dataType: "text",
      label: "Name",
      hint: null,
      required: true,
      readOnly: false,
      relevant: true,
      value: "father",
      valid: true,
      errors: [],
      choices: [],
    },
  ],
};

export const blockedEnd: PreviewState = {
  ...emptyState,
  progress: [8, 8],
  hasPrevious: true,
  canFinalize: false,
  blockers: ["members[i1].age", "members[i2].age", "visits[i3].note"],
};

export const nullTrace: TraceNode = {
  op: "and",
  args: [
    {
      op: "eq",
      args: [
        { op: "ref", path: "consent", args: [], result: "yes" },
        { op: "lit", literal: "yes", args: [], result: "yes" },
      ],
      result: true,
    },
    {
      op: "gt",
      args: [
        { op: "ref", path: "age", args: [], result: null },
        { op: "lit", literal: 18, args: [], result: 18 },
      ],
      result: null,
    },
  ],
  result: null,
};

export interface FakeEngine extends EngineModule {
  calls: { name: string; args: string[] }[];
  /** What the next operations return, in order; the last one repeats. */
  queue: PreviewState[];
}

/** An engine whose every operation returns the next queued state. */
export function fakeEngine(
  first: PreviewState,
  ...rest: PreviewState[]
): FakeEngine {
  const queue = [first, ...rest];
  const calls: { name: string; args: string[] }[] = [];
  // `previewState` reads the current state; every operation moves to the
  // next queued one (the last repeats), so a test can say what "the engine
  // answered" for each action it takes.
  const respond =
    (name: string) =>
    (...args: string[]) => {
      calls.push({ name, args });
      if (name !== "previewState" && queue.length > 1) queue.shift();
      return JSON.stringify(queue[0]);
    };
  return {
    calls,
    queue,
    engineVersion: () => "fake",
    previewOpen: (...args: string[]) => {
      calls.push({ name: "previewOpen", args });
      return JSON.stringify({
        handle: `s${String(calls.filter((c) => c.name === "previewOpen").length)}`,
      });
    },
    previewClose: (...args: string[]) => {
      calls.push({ name: "previewClose", args });
      return "{}";
    },
    previewState: respond("previewState"),
    previewSet: respond("previewSet"),
    previewNext: respond("previewNext"),
    previewPrevious: respond("previewPrevious"),
    previewEnter: respond("previewEnter"),
    previewLeave: respond("previewLeave"),
    previewAddRow: respond("previewAddRow"),
    previewDeleteRow: respond("previewDeleteRow"),
    previewGoToFirstBlocking: respond("previewGoToFirstBlocking"),
    previewTrace: (...args: string[]) => {
      calls.push({ name: "previewTrace", args });
      return JSON.stringify(nullTrace);
    },
  };
}
