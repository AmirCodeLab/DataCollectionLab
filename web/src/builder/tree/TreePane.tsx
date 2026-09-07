/** The form as a tree: what the form is, where you edit (scope §3).
 *
 * Every row is a node of the document, in document order, and what it says
 * beside itself comes from the server's plan (`badges.ts`). Moving a node is
 * refused at drag time where §2.3 and §11.1 would refuse it at compile — the
 * tree names the reason on the target, and the compile error stays the
 * backstop. Selection here is the selection everywhere (the properties pane
 * edits it, the plan highlights it).
 */

import { useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragOverEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import clsx from "clsx";

import {
  displayLabel,
  dropRefusal,
  find,
  isContainer,
  isGroup,
  isQuestion,
  isRepeat,
  type FormIr,
  type IrNode,
  type NodePath,
  type Slot,
} from "@/builder/ir";
import { useBuilder, type CompileStatus } from "@/builder/store";
import { AddMenu } from "./AddMenu";
import { badgeFor, type BadgeTone } from "./badges";
import { planDrop, type DropData } from "./drop";

const TONE: Record<BadgeTone, string> = {
  screen: "bg-blue-50 text-blue-800 border-blue-200",
  computed: "bg-slate-100 text-slate-700 border-slate-300",
  roster: "bg-violet-50 text-violet-800 border-violet-200",
  never: "bg-amber-50 text-amber-800 border-amber-200",
};

/** Whether the plan the store holds describes the current document. */
function planFreshness(status: CompileStatus): "fresh" | "stale" | "none" {
  if (status === "current") return "fresh";
  if (status === "stale" || status === "pending") return "stale";
  return "none";
}

export function TreePane() {
  const ir = useBuilder((s) => s.ir);
  const select = useBuilder((s) => s.select);
  const selectedId = useBuilder((s) => s.selectedId);
  const move = useBuilder((s) => s.move);
  const [dragging, setDragging] = useState<string | null>(null);
  const [hover, setHover] = useState<{
    id: string;
    refusal: string | null;
  } | null>(null);
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
  );

  if (ir === null) return <p className="text-sm text-slate-500">No form.</p>;

  const onDragStart = (event: DragStartEvent) => {
    setDragging(String(event.active.id));
  };
  const onDragOver = (event: DragOverEvent) => {
    const data = event.over?.data.current as DropData | undefined;
    if (event.over === null || data === undefined) {
      setHover(null);
      return;
    }
    const { refusal } = planDrop(ir, String(event.active.id), data);
    setHover({ id: String(event.over.id), refusal });
  };
  const onDragEnd = (event: DragEndEvent) => {
    const data = event.over?.data.current as DropData | undefined;
    setDragging(null);
    setHover(null);
    if (data === undefined) return;
    const { slot, refusal } = planDrop(ir, String(event.active.id), data);
    if (refusal !== null) return;
    move(String(event.active.id), slot);
  };

  const draggingNode =
    dragging === null ? null : (find(ir, dragging)?.node ?? null);

  return (
    <div className="text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => select(null)}
          className={clsx(
            "rounded px-1.5 py-0.5 text-start font-medium hover:bg-slate-50",
            selectedId === null && "bg-slate-100",
          )}
          aria-current={selectedId === null ? "true" : undefined}
        >
          {displayTitle(ir)}
        </button>
        <AddMenu />
      </div>
      <DndContext
        sensors={sensors}
        onDragStart={onDragStart}
        onDragOver={onDragOver}
        onDragEnd={onDragEnd}
        onDragCancel={() => {
          setDragging(null);
          setHover(null);
        }}
      >
        <NodeList
          ir={ir}
          list={ir.children}
          parentId={null}
          depth={0}
          hover={hover}
        />
        <DropSlot
          id="end:root"
          data={{
            slot: { parentId: null, index: ir.children.length },
            label: "at the end of the form",
          }}
          hover={hover}
          depth={0}
        />
        <DragOverlay>
          {draggingNode !== null && (
            <div className="rounded border border-slate-300 bg-white px-2 py-1 text-xs shadow">
              {displayLabel(draggingNode, ir)}
            </div>
          )}
        </DragOverlay>
      </DndContext>
      {ir.children.length === 0 && (
        <p className="mt-2 text-xs text-slate-500">
          Nothing yet. Add a question, a group or a repeat.
        </p>
      )}
    </div>
  );
}

function displayTitle(ir: FormIr): string {
  const title = ir.title[ir.defaultLanguage];
  if (typeof title === "string" && title !== "") return title;
  return ir.formId === "" ? "Form" : ir.formId;
}

interface HoverState {
  id: string;
  refusal: string | null;
}

function NodeList({
  ir,
  list,
  parentId,
  depth,
  hover,
}: {
  ir: FormIr;
  list: IrNode[];
  parentId: string | null;
  depth: number;
  hover: HoverState | null;
}) {
  return (
    <ul>
      {list.map((node, index) => (
        <li key={node.id}>
          <DropSlot
            id={`before:${node.id}`}
            data={{ slot: { parentId, index }, label: `before ${node.id}` }}
            hover={hover}
            depth={depth}
          />
          <NodeRow ir={ir} node={node} depth={depth} />
          {isContainer(node) && (
            <>
              <NodeList
                ir={ir}
                list={node.children}
                parentId={node.id}
                depth={depth + 1}
                hover={hover}
              />
              <DropSlot
                id={`into:${node.id}`}
                data={{
                  slot: { parentId: node.id, index: node.children.length },
                  label: `into ${node.id}`,
                }}
                hover={hover}
                depth={depth + 1}
              />
            </>
          )}
        </li>
      ))}
    </ul>
  );
}

function DropSlot({
  id,
  data,
  hover,
  depth,
}: {
  id: string;
  data: DropData;
  hover: HoverState | null;
  depth: number;
}) {
  const { setNodeRef, isOver } = useDroppable({ id, data });
  const hovered = hover?.id === id;
  const refusal = hovered ? hover.refusal : null;
  return (
    <div
      ref={setNodeRef}
      style={{ marginInlineStart: `${String(depth)}rem` }}
      className={clsx(
        "min-h-1 rounded transition-all",
        isOver && refusal === null && "my-0.5 h-1.5 bg-blue-300",
        isOver &&
          refusal !== null &&
          "my-0.5 bg-red-50 px-2 py-0.5 text-xs text-red-700",
      )}
      aria-label={isOver ? `drop ${data.label}` : undefined}
    >
      {isOver && refusal !== null && <span role="alert">{refusal}</span>}
    </div>
  );
}

function typeMarker(node: IrNode): string {
  if (isQuestion(node)) return node.dataType;
  if (isRepeat(node)) return "repeat";
  if (isGroup(node))
    return node.appearance === "field-list" ? "group · field-list" : "group";
  return "unrecognised node";
}

function NodeRow({
  ir,
  node,
  depth,
}: {
  ir: FormIr;
  node: IrNode;
  depth: number;
}) {
  const select = useBuilder((s) => s.select);
  const selectedId = useBuilder((s) => s.selectedId);
  const compile = useBuilder((s) => s.compile);
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: node.id,
  });
  const selected = selectedId === node.id;
  const known = isQuestion(node) || isContainer(node);

  const freshness = planFreshness(compile.status);
  const path = find(ir, node.id);
  const badge =
    freshness === "none" || path === null
      ? null
      : badgeFor(path, compile.result);

  return (
    <div
      ref={setNodeRef}
      style={{ marginInlineStart: `${String(depth)}rem` }}
      className={clsx(
        "group rounded px-1.5 py-0.5",
        selected ? "bg-slate-100" : "hover:bg-slate-50",
        isDragging && "opacity-40",
      )}
      data-node-id={node.id}
    >
      <div className="flex items-center gap-2">
        <button
          type="button"
          className="shrink-0 cursor-grab touch-none text-slate-400"
          aria-label={`drag ${node.id}`}
          {...attributes}
          {...listeners}
        >
          ⋮⋮
        </button>
        <button
          type="button"
          onClick={() => select(node.id)}
          aria-current={selected ? "true" : undefined}
          aria-label={`${known ? displayLabel(node, ir) : "unrecognised node"} (${node.id})`}
          className="flex min-w-0 flex-1 items-baseline gap-2 text-start"
        >
          <span className={clsx("truncate", !known && "italic text-slate-500")}>
            {known ? displayLabel(node, ir) : "unrecognised node"}
          </span>
          <code className="shrink-0 text-xs text-slate-500">{node.id}</code>
          <span className="hidden shrink-0 text-[11px] text-slate-400 xl:inline">
            {typeMarker(node)}
          </span>
        </button>
        {selected && path !== null && <RowActions ir={ir} path={path} />}
      </div>
      {badge !== null && (
        // Its own line, under the label: a badge beside the label sat over it
        // as soon as either grew, which the first end-to-end run showed on
        // every stale row. Nothing overlaps a line of its own.
        <span
          className={clsx(
            "ms-6 mt-0.5 inline-block rounded border px-1.5 py-0.5 text-[11px] leading-tight",
            TONE[badge.tone],
            freshness === "stale" && "opacity-50",
          )}
          title={
            freshness === "stale"
              ? "from an earlier compile; the plan is stale"
              : undefined
          }
        >
          {badge.text}
          {freshness === "stale" && <span className="ms-1">(stale)</span>}
        </span>
      )}
    </div>
  );
}

/** Keyboard-reachable moves and the delete, for the selected row only. */
function RowActions({ ir, path }: { ir: FormIr; path: NodePath }) {
  const move = useBuilder((s) => s.move);
  const remove = useBuilder((s) => s.remove);
  const [confirming, setConfirming] = useState(false);
  const id = path.node.id;
  const parentId = path.parent?.id ?? null;
  const siblings = path.parent === null ? ir.children : path.parent.children;

  const tryMove = (slot: Slot) => {
    if (dropRefusal(ir, id, slot.parentId) === null) move(id, slot);
  };
  const descendants = countDescendants(path.node);

  if (confirming) {
    return (
      <span className="flex items-center gap-1 text-xs" role="alertdialog">
        <span>
          delete <code>{id}</code>
          {descendants > 0 && ` and its ${String(descendants)} children`}?
        </span>
        <button
          type="button"
          onClick={() => remove(id)}
          className="rounded bg-red-600 px-1.5 text-white"
        >
          delete
        </button>
        <button
          type="button"
          onClick={() => setConfirming(false)}
          className="rounded border px-1.5"
        >
          cancel
        </button>
      </span>
    );
  }

  return (
    <span className="flex items-center gap-0.5 text-xs text-slate-500">
      <button
        type="button"
        aria-label="move up"
        disabled={path.index === 0}
        onClick={() => tryMove({ parentId, index: path.index - 1 })}
        className="rounded px-1 hover:bg-slate-200 disabled:opacity-30"
      >
        ▲
      </button>
      <button
        type="button"
        aria-label="move down"
        disabled={path.index >= siblings.length - 1}
        onClick={() => tryMove({ parentId, index: path.index + 2 })}
        className="rounded px-1 hover:bg-slate-200 disabled:opacity-30"
      >
        ▼
      </button>
      {path.parent !== null && (
        <button
          type="button"
          aria-label="move out of the container"
          onClick={() => {
            const grand = path.ancestors[path.ancestors.length - 2];
            const parentPath = find(ir, path.parent!.id);
            if (parentPath === null) return;
            tryMove({
              parentId: grand?.id ?? null,
              index: parentPath.index + 1,
            });
          }}
          className="rounded px-1 hover:bg-slate-200"
        >
          ⇤
        </button>
      )}
      <button
        type="button"
        aria-label={`delete ${id}`}
        onClick={() => setConfirming(true)}
        className="rounded px-1 text-red-700 hover:bg-red-50"
      >
        ✕
      </button>
    </span>
  );
}

function countDescendants(node: IrNode): number {
  if (!isContainer(node)) return 0;
  return node.children.reduce((n, child) => n + 1 + countDescendants(child), 0);
}
