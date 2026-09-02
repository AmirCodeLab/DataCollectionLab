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
    counts = {
        severity: sum(1 for d in result.diagnostics if d.severity == severity)
        for severity in _SEVERITY_ORDER
    }
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
    else:
        add("## This form cannot be published yet")
        add("")
        add(
            f"{counts['error']} problem(s) below would change what the form asks or "
            "collects. The form was still imported in full so that you can see "
            "everything at once, but it cannot be deployed until they are resolved."
        )
    add("")

    add("## What came through")
    add("")
    add("| | |")
    add("|---|---|")
    add(f"| Questions imported | {result.questions} |")
    add(f"| Rows read from the `survey` sheet | {result.survey_rows} |")
    add(f"| Languages | {', '.join(result.languages) or '—'} |")
    add(f"| Errors | {counts['error']} |")
    add(f"| Warnings | {counts['warning']} |")
    add(f"| Notes | {counts['info']} |")
    add("")

    grouped = _group(result.diagnostics)
    for severity in _SEVERITY_ORDER:
        codes = grouped.get(severity)
        if not codes:
            continue
        heading = {"error": "Errors", "warning": "Warnings", "info": "Notes"}[severity]
        add(f"## {heading}")
        add("")
        add(_SEVERITY_BLURB[severity])
        add("")
        for code, entries in sorted(codes.items()):
            add(f"### {code.replace('_', ' ')} ({len(entries)})")
            add("")
            # One remedy per group, not per row: it is the same advice every
            # time, and repeating it 135 times is how a report stops being read.
            remedy = next((e.remedy for e in entries if e.remedy), None)
            # Whether one sentence covers the group decides the shape of the
            # table. Printing the first entry's message as a heading over rows
            # that say different things is worse than printing nothing: it
            # reads as a statement about all of them and is true of one.
            # `unknown reference` is the case that found this — five rows, five
            # different missing names.
            uniform = len({e.message for e in entries}) == 1
            if uniform:
                add(f"{entries[0].message}")
                add("")
            if len(entries) > 1:
                if uniform:
                    add("| Where | In the spreadsheet |")
                    add("|---|---|")
                else:
                    add("| Where | What happened | In the spreadsheet |")
                    add("|---|---|---|")
                for entry in entries:
                    value = (entry.cell_value or "").replace("|", "\\|")
                    if len(value) > 60:
                        value = value[:57] + "…"
                    value_cell = f"`{value}`" if value else ""
                    if uniform:
                        add(f"| {_where(entry)} | {value_cell} |")
                    else:
                        message = entry.message.replace("|", "\\|")
                        add(f"| {_where(entry)} | {message} | {value_cell} |")
                add("")
            else:
                if not uniform:
                    add(f"{entries[0].message}")
                    add("")
                add(f"- **Where:** {_where(entries[0])}")
                if entries[0].cell_value:
                    add(f"- **Cell contains:** `{entries[0].cell_value}`")
                add("")
            if remedy:
                add(f"**What to do:** {remedy}")
                add("")

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
        "produced part of the form or is named above."
    )
    add("")
    return "\n".join(lines)


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
