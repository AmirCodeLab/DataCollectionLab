/** The Form IR document as the builder holds it (Form IR §1–§3, §7).
 *
 * Typed loosely on purpose. The scope doc's governing sentence is that **the
 * builder is an editor of a document it did not necessarily write**: an author
 * may download the IR, hand-edit it, and upload it back, and the builder must
 * not rewrite what it does not understand on reopen. So every node keeps an
 * index signature, every operation spreads what it does not recognise, and an
 * untouched subtree is returned as the same object it was loaded as — which is
 * what makes "load never mutates" testable by identity rather than by diff.
 *
 * Nothing here decides what a form means. There is no evaluation, no screen
 * plan and no diagnostic: those are `POST /forms/compile`'s answers. The one
 * rule this file enforces — where a repeat may sit — is a drop refusal the
 * scope doc asks the tree to make at drag time, with the compile error as the
 * backstop, not the message.
 */

export type Expr = { op: string } & Record<string, unknown>;
export type I18n = Record<string, string>;

interface NodeBase {
  type: string;
  id: string;
  label?: I18n;
  relevant?: Expr;
  [key: string]: unknown;
}

export interface ChoiceItem {
  value: string;
  label: I18n;
  [key: string]: unknown;
}

export interface InlineChoices {
  kind: "inline";
  items: ChoiceItem[];
  [key: string]: unknown;
}

export interface DatasetChoices {
  kind: "dataset";
  dataset: string;
  valueColumn: string;
  labelColumn: I18n;
  filter?: Expr;
  [key: string]: unknown;
}

export type ChoiceSource = InlineChoices | DatasetChoices;

export interface RowItem {
  value: string;
  label?: I18n;
  [key: string]: unknown;
}

export interface InlineRowSource {
  kind: "inline";
  items: RowItem[];
  bind?: Record<string, string>;
  allowAdd?: boolean;
  allowDelete?: boolean;
  [key: string]: unknown;
}

export interface DatasetRowSource {
  kind: "dataset";
  dataset: string;
  labelColumn?: I18n;
  filter?: Expr;
  bind?: Record<string, string>;
  allowAdd?: boolean;
  allowDelete?: boolean;
  [key: string]: unknown;
}

export type RowSource = InlineRowSource | DatasetRowSource;

export interface QuestionNode extends NodeBase {
  type: "question";
  dataType: string;
  hint?: I18n;
  required?: Expr | boolean;
  readOnly?: Expr | boolean;
  constraint?: Expr;
  constraintMessage?: I18n;
  severity?: "error" | "warning";
  calculate?: Expr;
  default?: Expr;
  sensitive?: boolean;
  appearance?: string;
  choices?: ChoiceSource;
  labelArgs?: Expr[];
  constraintMessageArgs?: Expr[];
}

export interface GroupNode extends NodeBase {
  type: "group";
  appearance?: string;
  children: IrNode[];
}

export interface RepeatNode extends NodeBase {
  type: "repeat";
  children: IrNode[];
  countExpr?: Expr;
  rowSource?: RowSource;
  minInstances?: number;
  maxInstances?: number;
  addLabel?: I18n;
  summaryLabel?: I18n;
  summaryLabelArgs?: Expr[];
}

/** A node type this builder does not know. Kept, shown, never rewritten. */
export interface ForeignNode extends NodeBase {
  children?: IrNode[];
}

export type IrNode = QuestionNode | GroupNode | RepeatNode | ForeignNode;
export type ContainerNode = GroupNode | RepeatNode;

export interface FormIr {
  irVersion: string;
  formId: string;
  version: number;
  title: I18n;
  defaultLanguage: string;
  languages: string[];
  children: IrNode[];
  [key: string]: unknown;
}

export const isQuestion = (node: IrNode): node is QuestionNode =>
  node.type === "question";
export const isGroup = (node: IrNode): node is GroupNode =>
  node.type === "group";
export const isRepeat = (node: IrNode): node is RepeatNode =>
  node.type === "repeat";
export const isContainer = (node: IrNode): node is ContainerNode =>
  isGroup(node) || isRepeat(node);

/** Form IR §2.4. */
export const ID_PATTERN = /^[a-z][a-z0-9_]*$/;

export const isExpr = (value: unknown): value is Expr =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as { op?: unknown }).op === "string";

// --- Reading -----------------------------------------------------------------

export interface NodePath {
  node: IrNode;
  /** `null` at the root. */
  parent: ContainerNode | null;
  index: number;
  /** Outermost first. */
  ancestors: ContainerNode[];
  /** The repeat this node sits in, if any — a repeat is the one container
   *  that creates a data scope (§2.3). */
  repeat: RepeatNode | null;
}

export function walk(ir: FormIr, visit: (path: NodePath) => void): void {
  const descend = (
    list: IrNode[],
    parent: ContainerNode | null,
    ancestors: ContainerNode[],
  ): void => {
    list.forEach((node, index) => {
      const repeat = [...ancestors].reverse().find(isRepeat) ?? null;
      visit({ node, parent, index, ancestors, repeat });
      if (isContainer(node)) descend(node.children, node, [...ancestors, node]);
    });
  };
  descend(ir.children, null, []);
}

export function find(ir: FormIr, id: string): NodePath | null {
  let found: NodePath | null = null;
  walk(ir, (path) => {
    if (found === null && path.node.id === id) found = path;
  });
  return found;
}

export function allIds(ir: FormIr): Set<string> {
  const ids = new Set<string>();
  walk(ir, ({ node }) => ids.add(node.id));
  return ids;
}

/** A §2.4 identifier not yet in the form, from whatever the author typed. */
export function uniqueId(ir: FormIr, base: string): string {
  const cleaned =
    base
      .toLowerCase()
      .replace(/[^a-z0-9_]+/g, "_")
      .replace(/^[^a-z]+/, "")
      .replace(/_+$/, "") || "q";
  const taken = allIds(ir);
  if (!taken.has(cleaned)) return cleaned;
  for (let n = 2; ; n += 1) {
    const candidate = `${cleaned}_${n}`;
    if (!taken.has(candidate)) return candidate;
  }
}

export interface FieldRef {
  id: string;
  dataType: string;
  sensitive: boolean;
  /** The enclosing repeat's id, or `null` at form level. */
  repeatId: string | null;
  /** Container ids, outermost first — for grouping a picker. */
  containers: string[];
  label: string;
}

/** Every question, in document order, with what a reference picker needs. */
export function fields(ir: FormIr): FieldRef[] {
  const out: FieldRef[] = [];
  walk(ir, ({ node, ancestors, repeat }) => {
    if (!isQuestion(node)) return;
    out.push({
      id: node.id,
      dataType: node.dataType,
      sensitive: node.sensitive === true,
      repeatId: repeat?.id ?? null,
      containers: ancestors.map((a) => a.id),
      label: displayLabel(node, ir),
    });
  });
  return out;
}

/** The label in the default language, falling back to any language, then
 *  the id — what the tree shows beside a node. */
export function displayLabel(node: IrNode, ir: FormIr): string {
  const label = node.label;
  if (label && typeof label === "object") {
    const preferred = label[ir.defaultLanguage];
    if (typeof preferred === "string" && preferred !== "") return preferred;
    const any = Object.values(label).find(
      (v) => typeof v === "string" && v !== "",
    );
    if (any !== undefined) return any;
  }
  return node.id;
}

// --- Editing -----------------------------------------------------------------
//
// Every operation returns a new document that shares every unchanged subtree
// with the old one. A node the author did not touch is the same object after
// the edit, so a save of an untouched form sends the bytes it loaded.

function mapTree(
  list: IrNode[],
  fn: (node: IrNode) => IrNode | null,
): IrNode[] {
  let changed = false;
  const out: IrNode[] = [];
  for (const node of list) {
    const replaced = fn(node);
    if (replaced === null) {
      changed = true;
      continue;
    }
    let next = replaced;
    if (isContainer(next)) {
      const children = mapTree(next.children, fn);
      if (children !== next.children) next = { ...next, children };
    }
    if (next !== node) changed = true;
    out.push(next);
  }
  return changed ? out : list;
}

function withChildren(ir: FormIr, children: IrNode[]): FormIr {
  return children === ir.children ? ir : { ...ir, children };
}

export function updateNode(
  ir: FormIr,
  id: string,
  patch: (node: IrNode) => IrNode,
): FormIr {
  return withChildren(
    ir,
    mapTree(ir.children, (node) => (node.id === id ? patch(node) : node)),
  );
}

/** Set one property, or remove it when `value` is `undefined` — an absent
 *  key and an explicit `null` are different things in the IR. */
export function setNodeProperty(
  ir: FormIr,
  id: string,
  key: string,
  value: unknown,
): FormIr {
  return updateNode(ir, id, (node) => {
    if (value === undefined) {
      if (!(key in node)) return node;
      return Object.fromEntries(
        Object.entries(node).filter(([k]) => k !== key),
      ) as IrNode;
    }
    if (node[key] === value) return node;
    return { ...node, [key]: value };
  });
}

export function removeNode(ir: FormIr, id: string): FormIr {
  return withChildren(
    ir,
    mapTree(ir.children, (node) => (node.id === id ? null : node)),
  );
}

/** Where a node goes: inside `parentId` (`null` for the root) at `index`. */
export interface Slot {
  parentId: string | null;
  index: number;
}

function insertAt(list: IrNode[], index: number, node: IrNode): IrNode[] {
  const at = Math.max(0, Math.min(index, list.length));
  return [...list.slice(0, at), node, ...list.slice(at)];
}

export function insertNode(ir: FormIr, slot: Slot, node: IrNode): FormIr {
  if (slot.parentId === null) {
    return { ...ir, children: insertAt(ir.children, slot.index, node) };
  }
  const parentId = slot.parentId;
  return withChildren(
    ir,
    mapTree(ir.children, (candidate) => {
      if (candidate.id !== parentId || !isContainer(candidate))
        return candidate;
      return {
        ...candidate,
        children: insertAt(candidate.children, slot.index, node),
      };
    }),
  );
}

const subtreeHasRepeat = (node: IrNode): boolean =>
  isRepeat(node) || (isContainer(node) && node.children.some(subtreeHasRepeat));

const isFieldList = (node: IrNode): boolean =>
  isGroup(node) && node.appearance === "field-list";

/** Why `id` cannot be dropped into `parentId`, or `null` when it can.
 *
 * The two refusals are §2.3 (a repeat cannot nest) and §11.1 (a repeat is one
 * screen and a field-list is one screen, and a subtree cannot be both). The
 * tree refuses at drag time so the author learns where the thing can go; the
 * compile error is the backstop, not the message.
 */
export function dropRefusal(
  ir: FormIr,
  id: string,
  parentId: string | null,
): string | null {
  const moving = find(ir, id);
  if (moving === null) return "nothing to move";
  if (parentId === null) return null;
  if (parentId === id) return "a node cannot contain itself";
  const target = find(ir, parentId);
  if (target === null) return "no such container";
  if (!isContainer(target.node))
    return "only a group or a repeat can hold questions";
  if (target.ancestors.some((a) => a.id === id)) {
    return "a node cannot be moved inside itself";
  }
  if (subtreeHasRepeat(moving.node)) {
    const chain = [...target.ancestors, target.node];
    if (chain.some(isRepeat)) {
      return "a repeat cannot sit inside a repeat (Form IR §2.3)";
    }
    if (chain.some(isFieldList)) {
      return "a repeat cannot sit inside a field-list group — each is one screen (§11.1)";
    }
  }
  return null;
}

/** Move a node to a slot. Throws the refusal; callers ask `dropRefusal`
 *  first, which is what the tree does while dragging. */
export function moveNode(ir: FormIr, id: string, slot: Slot): FormIr {
  const refusal = dropRefusal(ir, id, slot.parentId);
  if (refusal !== null) throw new Error(refusal);
  const path = find(ir, id);
  if (path === null) return ir;
  // Removing first shifts the indices in the same list; correct for it so
  // "drop after the third sibling" means what it looked like.
  let index = slot.index;
  const sameList =
    (path.parent === null && slot.parentId === null) ||
    (path.parent !== null && path.parent.id === slot.parentId);
  if (sameList && path.index < index) index -= 1;
  const without = removeNode(ir, id);
  return insertNode(without, { parentId: slot.parentId, index }, path.node);
}

export function setForm(ir: FormIr, patch: Partial<FormIr>): FormIr {
  let changed = false;
  for (const [key, value] of Object.entries(patch)) {
    if (ir[key] !== value) changed = true;
  }
  return changed ? { ...ir, ...patch } : ir;
}

// --- Making ------------------------------------------------------------------

export function newQuestion(
  id: string,
  dataType: string,
  language: string,
): QuestionNode {
  return { type: "question", id, dataType, label: { [language]: id } };
}

export function newGroup(id: string, language: string): GroupNode {
  return { type: "group", id, label: { [language]: id }, children: [] };
}

export function newRepeat(id: string, language: string): RepeatNode {
  // Enumerator-driven and unbounded above until the author says otherwise:
  // the one of §2.3's four sources that needs nothing else to be valid.
  return {
    type: "repeat",
    id,
    label: { [language]: id },
    minInstances: 0,
    children: [],
  };
}

export function emptyForm(
  formId: string,
  title: string,
  language = "en",
): FormIr {
  return {
    irVersion: "0.1",
    formId,
    version: 1,
    title: { [language]: title },
    defaultLanguage: language,
    languages: [language],
    children: [],
  };
}

/** Whether a value the API returned is a document this editor can open, and
 *  why not when it is not.
 *
 * Loose on purpose — a draft is allowed not to compile — but the tree needs a
 * `children` list and the header fields it edits need their §1 shapes. A
 * document that fails this is not rewritten into shape: the page offers it
 * as IR to view, download and replace, which is the floor the scope doc
 * promises for anything the builder cannot express. Absent header fields are
 * filled with §1's defaults, since adding a key is not rewriting one.
 */
export function asFormIr(value: unknown): { ir: FormIr } | { reason: string } {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { reason: "the document is not an object" };
  }
  const record = value as Record<string, unknown>;
  if (!Array.isArray(record.children)) {
    return { reason: "the document has no `children` list (Form IR §1)" };
  }
  const isI18n = (v: unknown): v is I18n =>
    typeof v === "object" && v !== null && !Array.isArray(v);
  if ("title" in record && !isI18n(record.title)) {
    return { reason: "`title` is not a per-language object (Form IR §7)" };
  }
  if ("languages" in record && !Array.isArray(record.languages)) {
    return { reason: "`languages` is not a list (Form IR §1)" };
  }
  if (
    "defaultLanguage" in record &&
    typeof record.defaultLanguage !== "string"
  ) {
    return { reason: "`defaultLanguage` is not a string (Form IR §1)" };
  }
  const defaultLanguage =
    typeof record.defaultLanguage === "string" ? record.defaultLanguage : "en";
  return {
    ir: {
      irVersion: "0.1",
      formId: "",
      version: 1,
      title: {},
      defaultLanguage,
      languages: [defaultLanguage],
      ...record,
      children: record.children as IrNode[],
    },
  };
}
