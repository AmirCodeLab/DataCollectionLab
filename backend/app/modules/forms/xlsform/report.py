"""The import report, as a file a form author can be sent.

The API returns diagnostics as structured data because a console needs to link
to a row and a test needs to assert on a code. This produces the other thing
that is needed: one file, readable by the person who wrote the spreadsheet,
that can be attached to an email and understood without the platform in front
of them.

Two audiences, two shapes, and the difference matters more than it looks:

  the API response   grouped by nothing, ordered by nothing, every field its
                     own key — because the caller does the grouping
  this file          grouped by severity then by code, because 135 identical
                     "appearance was not imported" lines are one fact, and a
                     report that makes an author read them 135 times to find
                     the one error underneath is a report nobody reads twice

The Markdown is the canonical form; the HTML is the same content with enough
styling to survive being pasted into a mail client.
"""

from __future__ import annotations

import html
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime

from .diagnostics import Diagnostic
from .importer import ImportResult

_SEVERITY_ORDER = ("error", "warning", "info")

_SEVERITY_BLURB = {
    "error": (
        "**These stop the form being published.** Each one would change what is "
        "asked or what is collected, so the form is not usable until they are "
        "resolved."
    ),
    "warning": (
        "These did not stop the import. Something in the spreadsheet was not "
        "carried over, but the data you collect is unaffected."
    ),
    "info": "Things worth knowing that needed no decision.",
}


def _group(diagnostics: list[Diagnostic]) -> dict[str, dict[str, list[Diagnostic]]]:
    grouped: dict[str, dict[str, list[Diagnostic]]] = defaultdict(lambda: defaultdict(list))
    for diagnostic in diagnostics:
        grouped[diagnostic.severity][diagnostic.code].append(diagnostic)
    return grouped


def _where(diagnostic: Diagnostic) -> str:
    return str(diagnostic.ref) if diagnostic.ref else "—"


def render_markdown(result: ImportResult, *, source_name: str, form_id: str) -> str:
    """The report as Markdown."""
    diagnostics = result.diagnostics
    counts = {
        severity: sum(1 for d in diagnostics if d.severity == severity)
        for severity in _SEVERITY_ORDER
    }
    errors = [d for d in diagnostics if d.severity == "error"]
    roots = [d for d in errors if d.caused_by is None]
    cascades = [d for d in errors if d.caused_by is not None]
    ours = [d for d in roots if d.blame == "platform"]
    theirs = [d for d in roots if d.blame == "author"]

    lines: list[str] = []
    add = lines.append

    add(f"# Import report — {source_name}")
    add("")
    add(f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}")
    add("")

    if result.publishable:
        add("## This form imported cleanly")
        add("")
        add(
            f"All {result.questions} questions were imported and the form can be "
            "published. Anything listed below was not carried over but does not "
            "change what you collect."
        )
        add("")
    else:
        add("## What you need to know first")
        add("")
        # The distinction that decides whether somebody spends an evening on
        # this: a platform gap cannot be fixed in the spreadsheet, and telling
        # an author to try is worse than telling them nothing.
        if ours and theirs:
            add(
                f"**{len(theirs)} thing(s) to change in your form, and "
                f"{len(ours)} that this platform cannot do yet.** The second "
                "group is not something you can fix by editing the spreadsheet."
            )
        elif ours:
            add(
                f"**Nothing in your form is wrong.** All {len(ours)} problem(s) "
                "below are things this platform has not built yet. Editing the "
                "spreadsheet will not resolve them."
            )
        else:
            add(f"**{len(theirs)} thing(s) need changing in your form.**")
        add("")
        if cascades:
            add(
                f"A further {len(cascades)} error(s) are knock-on effects of those "
                "and are listed underneath the cause, not counted separately — "
                "fixing the cause resolves them."
            )
            add("")
        add(
            "The form was imported in full regardless, so you can see everything "
            "at once. It cannot be published until the errors are resolved."
        )
        add("")

    add("## What came through")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Questions imported | {result.questions} |")
    add(f"| Rows read from the `survey` sheet | {result.survey_rows} |")
    add(f"| Languages | {', '.join(result.languages) or '—'} |")
    add(f"| Problems to fix in the form | {len(theirs)} |")
    add(f"| Problems this platform must fix | {len(ours)} |")
    add(f"| Knock-on errors (fixed by the above) | {len(cascades)} |")
    add(f"| Warnings | {counts['warning']} |")
    add(f"| Notes | {counts['info']} |")
    add("")

    following: dict[str, list[Diagnostic]] = defaultdict(list)
    for diagnostic in diagnostics:
        if diagnostic.caused_by:
            following[diagnostic.caused_by].append(diagnostic)

    if ours:
        add("## Things this platform cannot do yet")
        add("")
        add(
            "**These are not mistakes in your spreadsheet.** The form is correct "
            "and this platform has not built the feature. Editing the file will "
            "not help; either wait, or use one of the substitutes suggested."
        )
        add("")
        _render_group(add, ours, following)

    if theirs:
        add("## Things to change in your form")
        add("")
        add(
            "Each of these would change what the form asks or what it collects, "
            "so the form cannot be published until they are resolved."
        )
        add("")
        _render_group(add, theirs, following)

    for severity, heading, blurb in (
        ("warning", "Warnings", _SEVERITY_BLURB["warning"]),
        ("info", "Notes", _SEVERITY_BLURB["info"]),
    ):
        entries = [d for d in diagnostics if d.severity == severity and d.caused_by is None]
        if not entries:
            continue
        add(f"## {heading}")
        add("")
        add(blurb)
        add("")
        _render_group(add, entries, following)

    add("## For the platform team")
    add("")
    add(
        "Counted so that what gets built next is decided by what forms actually "
        "use, rather than by guessing."
    )
    add("")
    for title, data in (
        ("XPath functions this form needed that the importer lacks",
         result.instrumentation.unsupported_functions),
        ("Question types the importer does not know",
         result.instrumentation.unsupported_types),
        ("Types imported but which no client can present yet",
         result.instrumentation.uncollectable_types),
    ):
        add(f"- **{title}:** " + (
            ", ".join(f"`{k}` ×{v}" for k, v in sorted(data.items())) if data else "none"
        ))
    add("")
    add(
        f"Coverage: {result.coverage['cells']} non-empty cells read; every one either "
        "produced part of the form or is named above. A cell that produced nothing "
        "and went unmentioned fails the import outright rather than reaching this "
        "report as silence."
    )
    add("")
    add(
        "**What that check cannot tell you.** It accounts for everything that was "
        "present; it is blind to nothing being present at all. An empty `survey` "
        "sheet has no cells to account for, so the coverage check is perfectly "
        "satisfied by a workbook containing no questions — the official ODK "
        "XLSForm Template imported to a valid, compilable form with zero questions "
        "and passed every check there was. Emptiness is therefore asked about "
        "separately, and a form with no questions is refused at publish rather "
        "than merely noted here."
    )
    add("")
    return "\n".join(lines)


def _render_group(
    add: Callable[[str], None],
    entries: list[Diagnostic],
    following: dict[str, list[Diagnostic]],
) -> None:
    """One heading per code, with any knock-on errors underneath their cause."""
    grouped: dict[str, list[Diagnostic]] = defaultdict(list)
    for diagnostic in entries:
        grouped[diagnostic.code].append(diagnostic)

    for code, items in sorted(grouped.items()):
        add(f"### {code.replace('_', ' ')} ({len(items)})")
        add("")
        remedy = next((e.remedy for e in items if e.remedy), None)
        uniform = len({e.message for e in items}) == 1
        if uniform:
            add(items[0].message)
            add("")
        named = any(e.node_id for e in items)
        if len(items) > 1:
            # One sentence above the table when it covers every row, and a
            # "Question" column when the rows are about named questions — a
            # table that repeats the same 40-word explanation once per row is
            # how a report stops being read.
            header = ["Where"]
            if named:
                header.append("Question")
            if not uniform:
                header.append("What happened")
            header.append("In the spreadsheet")
            add("| " + " | ".join(header) + " |")
            add("|" + "---|" * len(header))
            for entry in items:
                value = (entry.cell_value or "").replace("|", "\\|")
                if len(value) > 60:
                    value = value[:57] + "…"
                cells = [_where(entry)]
                if named:
                    cells.append(f"`{entry.node_id}`" if entry.node_id else "")
                if not uniform:
                    cells.append(entry.message.replace("|", "\\|"))
                cells.append(f"`{value}`" if value else "")
                add("| " + " | ".join(cells) + " |")
            add("")
        else:
            if not uniform:
                add(items[0].message)
                add("")
            add(f"- **Where:** {_where(items[0])}")
            if items[0].cell_value:
                add(f"- **Cell contains:** `{items[0].cell_value}`")
            add("")
        if remedy:
            add(f"**What to do:** {remedy}")
            add("")

        # The knock-ons, under the thing that caused them.
        knock_ons = [k for item in items for k in following.get(item.key or "", [])]
        if knock_ons:
            add(f"*Also stopped working because of the above ({len(knock_ons)}):*")
            add("")
            for entry in knock_ons:
                add(f"- {_where(entry)} — {entry.message}")
            add("")


def render_html(result: ImportResult, *, source_name: str, form_id: str) -> str:
    """The same report as a self-contained HTML file.

    Styling is inline and minimal on purpose: this gets forwarded, pasted into
    mail clients and printed, and a stylesheet reference would survive none of
    those.
    """
    markdown = render_markdown(result, source_name=source_name, form_id=form_id)
    body: list[str] = []
    in_table = False
    for line in markdown.splitlines():
        if line.startswith("| "):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):
                continue
            if not in_table:
                body.append("<table>")
                in_table = True
            tag = "td"
            body.append(
                "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"
            )
            continue
        if in_table:
            body.append("</table>")
            in_table = False
        if line.startswith("### "):
            body.append(f"<h3>{_inline(line[4:])}</h3>")
        elif line.startswith("## "):
            body.append(f"<h2>{_inline(line[3:])}</h2>")
        elif line.startswith("# "):
            body.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("- "):
            body.append(f"<p class='item'>{_inline(line[2:])}</p>")
        elif line.strip():
            body.append(f"<p>{_inline(line)}</p>")
    if in_table:
        body.append("</table>")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>Import report — {html.escape(source_name)}</title>
<style>
 body {{ font: 15px/1.55 -apple-system, Segoe UI, Roboto, sans-serif;
        max-width: 46rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
 h1 {{ font-size: 1.5rem; }} h2 {{ font-size: 1.15rem; margin-top: 2rem;
        border-bottom: 1px solid #ddd; padding-bottom: .3rem; }}
 h3 {{ font-size: 1rem; margin-top: 1.4rem; color: #444; }}
 table {{ border-collapse: collapse; width: 100%; margin: .6rem 0 1rem; }}
 td {{ border: 1px solid #e0e0e0; padding: .35rem .5rem; vertical-align: top;
        font-size: .9rem; }}
 code {{ background: #f4f4f4; padding: .1rem .3rem; border-radius: 3px;
        font-size: .87em; }}
 p.item {{ margin: .2rem 0 .2rem 1rem; }}
</style></head><body>
{chr(10).join(body)}
</body></html>
"""


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = escaped.replace("\\|", "|")
    # Markdown's `code` and **bold**, which is all this report uses.
    out: list[str] = []
    for index, part in enumerate(escaped.split("`")):
        out.append(f"<code>{part}</code>" if index % 2 else part)
    escaped = "".join(out)
    parts = escaped.split("**")
    return "".join(f"<strong>{p}</strong>" if i % 2 else p for i, p in enumerate(parts))
