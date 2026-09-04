# The XLSForm DCP accepts — a template and what it leaves out

**For:** RCons, so their questionnaire tool emits something this platform
imports without a round trip. **Written:** 4 September 2026.

Two workbooks in `docs/xlsform-template/`, with `districts.csv` beside them:

- **`dcp-xlsform-template.xlsx`** — build against this. Every question type DCP
  can collect today appears in it once, with relevance, constraints and an
  external choice list. **0 errors, 0 warnings**, every non-empty cell accounted
  for, and the IR it produces compiles on the reference engine.
- **`dcp-xlsform-roster-example.xlsx`** — the roster shape, which the importer
  **refuses** today. Read §5 before using it; it is in the pack so your tool
  emits the right thing now and needs no change when the refusal lifts.

Both have been run through our own importer. We are not handing over a template
we have never executed.

```bash
python scripts/import_xlsform.py docs/xlsform-template/dcp-xlsform-template.xlsx
#   exit 0, and a report in .md and .html naming anything it could not take
```

Run that against your own output. Exit 0 means it imports; the report names
every cell that produced nothing, which is the thing worth reading.

---

## 1. The three sheets

`survey`, `choices`, `settings` — standard XLSForm. `settings` must carry
`form_title`, `form_id`, `version` and `default_language`.

Labels are per language, `label::English (en)`. Anything after `::` becomes the
language key, so use the same spelling in every column. The template carries
English and Urdu.

---

## 2. Question types we can collect

These ten are what a phone can present today. **The template uses every one of
them**, so the workbook is the reference for the exact spelling.

| Type | Notes |
|---|---|
| `text` | |
| `integer` | |
| `decimal` | |
| `date` | |
| `select_one <list>` | list from the `choices` sheet |
| `select_multiple <list>` | |
| `select_one_from_file <file>.csv` | external list, see §4 |
| `note` | display only, stores no answer |
| `image` | camera or gallery |
| `geopoint` | one GPS point |
| `signature` | |

Plus the structural rows: `begin group` / `end group` and `calculate`.
`begin repeat` / `end repeat` parse correctly and are **refused** — see §5.

### Types that are in our specification and that a phone cannot yet show

These import without complaint at the document level and then reach an
enumerator as a question they cannot answer, so **the importer refuses them**
rather than letting them through. Do not emit them:

`boolean`, `time`, `datetime`, `barcode`, `audio`, `video`, `file`, `drawing`,
`geotrace`, `geoshape`.

`time` is the first candidate for the next version. `boolean` is not a gap in
practice: XLSForm has no boolean of its own, so yes/no arrives as a
`select_one`, which is what the template does.

### Types that are not in our specification at all

`rank` and `range`. There is nothing to map them to.

---

## 3. Relevance and constraints are declarative, not skip-to

**This is the one real difference from your current system.** You express
navigation as ordered jumps — *after q8, if q8==1 go to q10*. DCP, like XLSForm
and SurveyCTO, states for each question the condition under which it applies:

```
relevant:    ${owns_land} = 'yes'
constraint:  ${member_age} >= 0 and ${member_age} < 120
```

A question with no `relevant` is always asked. A question with one is asked
only when it evaluates true, and the runtime works out the order — there is no
"go to" and nothing names a destination. A rule that in your system jumps over
five questions becomes five `relevant` expressions, one per question skipped,
not one rule on the jump.

**Operators and functions that survive the import:** `and`, `or`, `not`, the
comparisons, `+ - * div mod`, and `count`, `sum`, `min`, `max`,
`count-selected`, `selected`, `coalesce`, `today`, `now`, `string-length`,
`upper-case`, `lower-case`, `normalize-space`, `concat`, `substr`, `contains`,
`starts-with`, `ends-with`, `regex`, `round`, `int`, `number`, `string`.

Anything else is reported by name and cell rather than silently dropped, which
is why the report is worth reading even when the import succeeds.

`constraint_message::<language>` is worth filling in. A refusal with no message
is a form the enumerator cannot get past and cannot explain.

---

## 4. External choice lists

`select_one_from_file districts.csv`, with the CSV shipped beside the workbook.
It needs a `name` column and a `label` column; `name` is what is stored and
`label` is what is shown.

Send the CSV with the workbook. A file the survey sheet names and we cannot
find is an error naming the file — never a question that quietly has no
options.

---

## 5. Rosters are refused today, and that is deliberate

A roster is `begin repeat` / `end repeat`, with the instance count from an
earlier answer:

```
repeat_count:  ${hh_size}
```

**The importer refuses a form containing one.** Not a warning — an error, and
the form cannot be published:

```
ERROR  survey row 6, column 'type'
       4 question(s) in this form cannot be asked by any client yet, so they
       would be silently skipped in the field: `member_name`, `member_age`,
       `member_relation`, `member_in_school`. They are inside a repeat, and
       this platform's form format excludes a repeat from the screen plan
       until repeat screen flow is built (Form IR §11.1).
```

**Why refusing rather than warning.** Until repeat screen flow is built, a form
with a roster imports, compiles, publishes, deploys, reaches a handset — and
asks none of the roster's questions. Nothing on any screen looks wrong, so
nobody reports anything, and the answers are missing with no trace of why. For a
household listing that is most of the survey. A form that collects nothing it
claims to collect must not deploy, which is the same rule that refuses a form
with no questions at all.

**The shape is still in the pack.** `dcp-xlsform-roster-example.xlsx` carries
exactly the roster your tool should emit, and running the importer over it shows
the refusal above. It is there so your tool emits the right thing now and needs
no change when the refusal lifts.

**When it lifts:** repeat screen flow is item 3 of the current phase
(`docs/phase3-pilot-scope.md` §5). The enumerator-driven roster — *keep adding
members until the respondent says stop* — is the same item; use `repeat_count`
until then.

---

## 6. What we do not support that your current forms use

From the analysis of your existing app (`docs/rcons-current-system.md` §5).
These are the ones your tool should not emit, in order of how often they appear:

| Your type | Count | What to emit instead |
|---|---|---|
| **Custom Multiple Selection** | 88 | `select_multiple`, if "custom" carries no behaviour beyond the list. **We need to see what it does first** |
| **Person Id** | 73 | **Nothing yet.** It appears to reference a roster member, which is cross-repeat referencing and a genuine feature gap rather than a widget. The single most important thing to tell us about |
| Input Field | 5 | Probably `text` / `integer` / `decimal` — tell us which |
| Custom Single Selection | 3 | `select_one`, same caveat as above |
| Time Picker | 2 | **Nothing yet.** `time` is in our specification with no widget |
| Enum Selection | 2 | Probably `select_one` — tell us what distinguishes it |
| **Structure Map** | 1 | **Nothing.** A map widget over `samples_polygon` / `samples_structure_points`. Not planned for the pilot |

Single Selection, Edit Text, Multiple Selection, Date Picker and Note all map
directly and are in the template.

**The four marked with counts we cannot map are the questions to answer**, and
`Person Id` is the one that changes scope if it means what it looks like it
means.

---

## 7. What to send back

1. One real questionnaire emitted by your tool as XLSForm, with any companion
   CSVs.
2. What `Custom`, `Input Field`, `Enum Selection` and especially `Person Id` do
   in your app.

We will run it through the importer and send you the report. The report names
every problem in one pass rather than stopping at the first, so one round trip
should be enough.
