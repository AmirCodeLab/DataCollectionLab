/** The engine in the browser: the contract between the console and the Kotlin
 * engine compiled to Wasm (docs/wasm-spike.md, option (a)).
 *
 * This is the same engine the handset runs, which is the whole point of
 * item 0's second binding decision: preview runs the engine, never an
 * approximation of it. Only strings cross the `@JsExport` boundary on wasmJs,
 * so the surface is JSON in and JSON out — the same boundary
 * `POST /forms/compile` has — and the shapes below are the contract the
 * Kotlin side (`PreviewSession` in `shared/form-engine`) produces. A change
 * to one is a change to both, in one commit.
 *
 * Nothing here decides anything about a form. Every relevance, value, label,
 * count and blocker on this page is read out of `PreviewState`, which the
 * engine wrote.
 */

/** A form value as `formValueToJson` writes it. */
export type EngineValue =
  | string
  | number
  | boolean
  | null
  | EngineValue[]
  | { [key: string]: EngineValue };

export interface PreviewError {
  kind: string;
  severity: "error" | "warning";
  /** The constraint message rendered by the engine (§7.1), or null. */
  message: string | null;
}

export interface PreviewQuestion {
  /** Where the engine keeps the state: `age`, or `members[i3].age`. */
  path: string;
  id: string;
  dataType: string;
  label: string;
  hint: string | null;
  required: boolean;
  readOnly: boolean;
  relevant: boolean;
  value: EngineValue;
  valid: boolean;
  errors: PreviewError[];
  choices: { value: string; label: string }[];
}

export interface PreviewRow {
  instanceId: string;
  /** §2.3's chain: summaryLabel, else the source row's label, else the position. */
  label: string;
  canDelete: boolean;
}

export interface PreviewRoster {
  repeatId: string;
  title: string;
  rows: PreviewRow[];
  canAdd: boolean;
  addLabel: string | null;
}

export interface PreviewScreen {
  index: number;
  kind: "questions" | "repeat";
  groupId: string | null;
  sectionId: string | null;
  repeatId: string | null;
  /** The container's label in the form's language, or null. */
  title: string | null;
}

export interface PreviewInside {
  repeatId: string;
  instanceId: string;
  rowLabel: string;
  /** 1-based screen within the row, of how many are relevant (§11.3). */
  within: [number, number];
  /** 1-based row of how many rows exist (§11.3). */
  across: [number, number];
}

/** Everything a preview renders, all of it the engine's answer. */
export interface PreviewState {
  screen: PreviewScreen | null;
  inside: PreviewInside | null;
  /** §11.2's form-level pair; a repeat counts once and it never moves inside a row. */
  progress: [number, number];
  hasNext: boolean;
  hasPrevious: boolean;
  /** The questions of the current screen (or instance screen), relevant or not. */
  questions: PreviewQuestion[];
  roster: PreviewRoster | null;
  canFinalize: boolean;
  /** Paths standing between this form and finalisation (§6.2). */
  blockers: string[];
  /** Every value the engine holds, by path — what a test case asserts over. */
  values: Record<string, EngineValue>;
  /** Every field state's relevance, by path. */
  relevant: Record<string, boolean>;
  /** Every field state's validity, by path. */
  valid: Record<string, boolean>;
}

/** One node of an expression, annotated with what it evaluated to. */
export interface TraceNode {
  op: string;
  fn?: string;
  path?: string;
  /** For `lit`: the literal. */
  literal?: EngineValue;
  args: TraceNode[];
  /** What this node came to, against the current answers. */
  result: EngineValue;
}

/** The property keys a trace can be asked for. */
export type TraceKey =
  | "relevant"
  | "constraint"
  | "calculate"
  | "required"
  | "readOnly"
  | "default"
  | "countExpr";

export interface EngineFailure {
  error: string;
}

/** The functions the Wasm module exports. Strings in, strings out. */
export interface EngineModule {
  engineVersion(): string;
  previewOpen(irJson: string, today: string): string;
  previewClose(handle: string): string;
  previewState(handle: string): string;
  previewSet(handle: string, path: string, valueJson: string): string;
  previewNext(handle: string): string;
  previewPrevious(handle: string): string;
  previewEnter(handle: string, repeatId: string, instanceId: string): string;
  previewLeave(handle: string): string;
  previewAddRow(handle: string, repeatId: string): string;
  previewDeleteRow(
    handle: string,
    repeatId: string,
    instanceId: string,
  ): string;
  previewGoToFirstBlocking(handle: string): string;
  previewTrace(handle: string, path: string, key: string): string;
}

function parse<T>(raw: string): T {
  const value: unknown = JSON.parse(raw);
  if (value && typeof value === "object" && "error" in value) {
    throw new Error(String((value as EngineFailure).error));
  }
  return value as T;
}

/**
 * One open form in the engine. Every method returns the engine's whole state
 * afterwards; the console keeps no state of its own about the form.
 */
export class PreviewSession {
  private constructor(
    private readonly engine: EngineModule,
    private readonly handle: string,
  ) {}

  static open(
    engine: EngineModule,
    ir: unknown,
    today: string,
  ): PreviewSession {
    const opened = parse<{ handle: string }>(
      engine.previewOpen(JSON.stringify(ir), today),
    );
    return new PreviewSession(engine, opened.handle);
  }

  state(): PreviewState {
    return parse<PreviewState>(this.engine.previewState(this.handle));
  }
  set(path: string, value: EngineValue): PreviewState {
    return parse<PreviewState>(
      this.engine.previewSet(this.handle, path, JSON.stringify(value)),
    );
  }
  next(): PreviewState {
    return parse<PreviewState>(this.engine.previewNext(this.handle));
  }
  previous(): PreviewState {
    return parse<PreviewState>(this.engine.previewPrevious(this.handle));
  }
  enter(repeatId: string, instanceId: string): PreviewState {
    return parse<PreviewState>(
      this.engine.previewEnter(this.handle, repeatId, instanceId),
    );
  }
  leave(): PreviewState {
    return parse<PreviewState>(this.engine.previewLeave(this.handle));
  }
  addRow(repeatId: string): PreviewState {
    return parse<PreviewState>(
      this.engine.previewAddRow(this.handle, repeatId),
    );
  }
  deleteRow(repeatId: string, instanceId: string): PreviewState {
    return parse<PreviewState>(
      this.engine.previewDeleteRow(this.handle, repeatId, instanceId),
    );
  }
  goToFirstBlocking(): PreviewState {
    return parse<PreviewState>(
      this.engine.previewGoToFirstBlocking(this.handle),
    );
  }
  trace(path: string, key: TraceKey): TraceNode {
    return parse<TraceNode>(this.engine.previewTrace(this.handle, path, key));
  }
  close(): void {
    this.engine.previewClose(this.handle);
  }
}
