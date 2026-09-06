/** The three picker decisions: everything shown and nothing scoped; the
 *  index forms spelled out; sensitive fields badged, never hidden. */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fixture } from "./fixture";
import { EVERY_INSTANCE, FIRST_INSTANCE, pickerGroups } from "./picker";
import { ReferencePicker } from "./ReferencePicker";

afterEach(cleanup);

describe("pickerGroups", () => {
  it("from inside a repeat: this instance first and unprefixed, then the rest", () => {
    const groups = pickerGroups(fixture(), "name");
    expect(groups.map((g) => g.title)).toEqual([
      "This instance — members",
      "Form",
      "hh",
    ]);
    expect(groups[0].entries.map((e) => e.path)).toEqual(["name", "income"]);
    expect(groups[0].entries.every((e) => e.note === null)).toBe(true);
    expect(groups[1].entries.map((e) => e.path)).toEqual(["age", "consent"]);
    expect(groups[2].entries.map((e) => e.path)).toEqual(["size"]);
  });

  it("from outside: an instance's field as what it is, with the index spelled out, and the aggregate beside it", () => {
    const groups = pickerGroups(fixture(), "age");
    expect(groups.map((g) => g.title)).toEqual(["Form", "hh", "hh › members"]);
    const members = groups[2].entries;
    expect(members.map((e) => e.path)).toEqual([
      "members[0].name",
      "members[].name",
      "members[0].income",
      "members[].income",
    ]);
    expect(members[0].note).toBe(FIRST_INSTANCE);
    expect(members[1].note).toBe(EVERY_INSTANCE);
    expect(members[1].aggregateOnly).toBe(true);
    expect(members[0].aggregateOnly).toBe(false);
  });

  it("shows a sensitive field, marked, wherever the author is", () => {
    const inside = pickerGroups(fixture(), "name").flatMap((g) => g.entries);
    const outside = pickerGroups(fixture(), "size").flatMap((g) => g.entries);
    expect(inside.find((e) => e.path === "income")?.sensitive).toBe(true);
    expect(
      outside.filter((e) => e.id === "income").map((e) => e.sensitive),
    ).toEqual([true, true]);
    // Nothing is scoped: every question is reachable from every node.
    expect(new Set(inside.map((e) => e.id)).size).toBe(5);
    expect(new Set(outside.map((e) => e.id)).size).toBe(5);
  });
});

describe("ReferencePicker", () => {
  it("lists the groups with the badge and the notes, and picks an entry", () => {
    const onPick = vi.fn();
    render(<ReferencePicker ir={fixture()} nodeId="age" onPick={onPick} />);
    fireEvent.click(screen.getByRole("button", { name: /insert field/i }));

    expect(screen.getAllByText("sensitive")).toHaveLength(2);
    expect(screen.getAllByText(FIRST_INSTANCE)).toHaveLength(2);
    expect(screen.getAllByText(EVERY_INSTANCE)).toHaveLength(2);

    fireEvent.click(screen.getByText("members[].income"));
    expect(onPick).toHaveBeenCalledTimes(1);
    expect(onPick.mock.calls[0][0]).toMatchObject({
      path: "members[].income",
      sensitive: true,
      aggregateOnly: true,
    });
  });

  it("filters by path or label without dropping a group's other entries", () => {
    render(<ReferencePicker ir={fixture()} nodeId="age" onPick={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /insert field/i }));
    fireEvent.change(screen.getByLabelText("Filter fields"), {
      target: { value: "inco" },
    });
    expect(screen.getByText("members[0].income")).toBeInTheDocument();
    expect(screen.queryByText("age")).toBeNull();
  });
});
