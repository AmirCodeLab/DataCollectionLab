/** The draft being edited: one document, one selection, one compile answer.
 *
 * A store rather than component state because three panes read it — the tree
 * edits, the properties edit, the plan checks — and a selection shared
 * between them is the rule in scope §3 ("selection is shared between the
 * views; editing is not").
 *
 * Two invariants live here and nowhere else:
 *
 * - **Load never mutates.** `ir` is the object the server returned until an
 *   edit replaces it, and every edit shares the subtrees it did not touch
 *   (`ir.ts`). `saved` is the object the server last acknowledged, so "unsaved
 *   changes" is `ir !== saved`, by identity.
 * - **The plan is never recomputed locally.** An edit does not touch the
 *   compile answer; it marks it stale. A compile answer is accepted only if
 *   the document it was asked for is still the current one — otherwise the
 *   answer describes a form the author no longer has, and stale it stays.
 *
 * Lives in its own module: a file exporting both a component and a store
 * cannot hot-reload (see `lib/autoRefresh.ts`).
 */

import { create } from "zustand";

import type { CompileResponse } from "@/api/types";
import {
  insertNode,
  moveNode,
  removeNode,
  setForm,
  setNodeProperty,
  updateNode,
  type FormIr,
  type IrNode,
  type Slot,
} from "./ir";

export type CompileStatus =
  /** Nothing asked yet. */
  | "idle"
  /** Asked, for the current document. */
  | "pending"
  /** The answer describes the current document. */
  | "current"
  /** The document changed after this answer; a new one is owed. */
  | "stale"
  /** The server refused the current document, with reasons. */
  | "refused"
  /** The request itself failed — network, 5xx. */
  | "failed";

export interface CompileState {
  status: CompileStatus;
  /** The last answer, kept while stale so the plan can still be read. */
  result: CompileResponse | null;
  /** §10 reasons, one per line, verbatim from the server. */
  refusals: string[];
  failure: string | null;
  /** The document the last request was for — the staleness check. */
  askedFor: FormIr | null;
}

export type SaveStatus = "clean" | "dirty" | "saving" | "conflict" | "failed";

export interface BuilderState {
  /** `form.id` — the row, not the §1 `formId` key. */
  formId: string | null;
  ir: FormIr | null;
  /** What the server last acknowledged; `null` before the first save of a
   *  new draft. */
  saved: FormIr | null;
  /** The revision `saved` has on the server; `null` until a draft exists. */
  revision: number | null;
  save: { status: SaveStatus; message: string | null };
  /** `null` selects the form header. */
  selectedId: string | null;
  compile: CompileState;

  open: (formId: string, ir: FormIr, revision: number | null) => void;
  close: () => void;
  select: (id: string | null) => void;

  /** Replace the whole document — IR pasted or uploaded (scope §1's floor). */
  replace: (ir: FormIr) => void;
  editForm: (patch: Partial<FormIr>) => void;
  editNode: (id: string, patch: (node: IrNode) => IrNode) => void;
  setProperty: (id: string, key: string, value: unknown) => void;
  insert: (slot: Slot, node: IrNode) => void;
  remove: (id: string) => void;
  move: (id: string, slot: Slot) => void;

  saveStarted: () => void;
  saveSucceeded: (sent: FormIr, revision: number) => void;
  saveConflicted: (message: string) => void;
  saveFailed: (message: string) => void;

  compileStarted: (askedFor: FormIr) => void;
  compileSucceeded: (askedFor: FormIr, result: CompileResponse) => void;
  compileRefused: (askedFor: FormIr, refusals: string[]) => void;
  compileFailed: (askedFor: FormIr, message: string) => void;
}

const idleCompile: CompileState = {
  status: "idle",
  result: null,
  refusals: [],
  failure: null,
  askedFor: null,
};

export const useBuilder = create<BuilderState>((set, get) => {
  /** Every edit goes through here: swap the document, mark the answer stale. */
  const edit = (next: FormIr): void => {
    const state = get();
    if (state.ir === null || next === state.ir) return;
    set({
      ir: next,
      save: {
        status: state.save.status === "conflict" ? "conflict" : "dirty",
        message: null,
      },
      compile:
        state.compile.status === "idle"
          ? state.compile
          : { ...state.compile, status: "stale" },
    });
  };

  return {
    formId: null,
    ir: null,
    saved: null,
    revision: null,
    save: { status: "clean", message: null },
    selectedId: null,
    compile: idleCompile,

    open: (formId, ir, revision) =>
      set({
        formId,
        ir,
        saved: revision === null ? null : ir,
        revision,
        save: { status: revision === null ? "dirty" : "clean", message: null },
        selectedId: null,
        compile: idleCompile,
      }),
    close: () =>
      set({
        formId: null,
        ir: null,
        saved: null,
        revision: null,
        save: { status: "clean", message: null },
        selectedId: null,
        compile: idleCompile,
      }),
    select: (id) => set({ selectedId: id }),

    replace: (ir) => {
      const state = get();
      if (state.ir === null) return;
      edit(ir);
      set({ selectedId: null });
    },
    editForm: (patch) => {
      const { ir } = get();
      if (ir !== null) edit(setForm(ir, patch));
    },
    editNode: (id, patch) => {
      const { ir } = get();
      if (ir !== null) edit(updateNode(ir, id, patch));
    },
    setProperty: (id, key, value) => {
      const { ir } = get();
      if (ir !== null) edit(setNodeProperty(ir, id, key, value));
    },
    insert: (slot, node) => {
      const { ir } = get();
      if (ir !== null) {
        edit(insertNode(ir, slot, node));
        set({ selectedId: node.id });
      }
    },
    remove: (id) => {
      const { ir, selectedId } = get();
      if (ir !== null) {
        edit(removeNode(ir, id));
        if (selectedId === id) set({ selectedId: null });
      }
    },
    move: (id, slot) => {
      const { ir } = get();
      if (ir !== null) edit(moveNode(ir, id, slot));
    },

    saveStarted: () => set({ save: { status: "saving", message: null } }),
    saveSucceeded: (sent, revision) => {
      const { ir } = get();
      set({
        saved: sent,
        revision,
        // An edit made while the request was in flight is still unsaved.
        save: { status: ir === sent ? "clean" : "dirty", message: null },
      });
    },
    saveConflicted: (message) => set({ save: { status: "conflict", message } }),
    saveFailed: (message) => set({ save: { status: "failed", message } }),

    compileStarted: (askedFor) =>
      set((state) => ({
        compile: { ...state.compile, status: "pending", askedFor },
      })),
    compileSucceeded: (askedFor, result) =>
      set((state) => ({
        compile: {
          status: askedFor === state.ir ? "current" : "stale",
          result,
          refusals: [],
          failure: null,
          askedFor,
        },
      })),
    compileRefused: (askedFor, refusals) =>
      set((state) => ({
        compile: {
          ...state.compile,
          status: askedFor === state.ir ? "refused" : "stale",
          refusals,
          failure: null,
          askedFor,
        },
      })),
    compileFailed: (askedFor, message) =>
      set((state) => ({
        compile: {
          ...state.compile,
          status: askedFor === state.ir ? "failed" : "stale",
          failure: message,
          askedFor,
        },
      })),
  };
});
