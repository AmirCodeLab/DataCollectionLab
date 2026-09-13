# The XLSForm DCP accepts — a template and what it leaves out

**For:** RCons, so their questionnaire tool emits something this platform
imports without a round trip.
**Written:** 4 September 2026. **Revised:** 12 September 2026, after importing a
questionnaire the size of yours — see §0.

Two workbooks in `docs/xlsform-template/`, with `districts.csv` beside them:

- **`dcp-xlsform-template.xlsx`** — build against this. Every question type DCP
  can collect today appears in it exactly once, with relevance, constraints, an
  external choice list, a `default`, and a group whose questions share one
  screen. Three languages. **0 errors, 0 warnings.**
- **`dcp-xlsform-roster-example.xlsx`** — the roster shape. Also **0 errors, 0
  warnings**; §5 is what an enumerator sees.

Both have been run through our own importer. We are not handing over a template
we have never executed.

```bash
python scripts/import_xlsform.py docs/xlsform-template/dcp-xlsform-template.xlsx
#   exit 0, and a report in .md and .html naming anything it could not take
```

Run that against your own output. Exit 0 means it imports; the report names
every cell that produced nothing, which is the thing worth reading.

---

## 0. We have now imported something the size of your questionnaire

On 12 September 2026 we built an instrument matching every number you gave us —
**95 sections, 2,128 questions, 7,080 options, three languages, your 45,327-row
school list and 4,035-row health facility list, two rosters** — and put it
through this pipeline end to end: imported, compiled, published, deployed, and
pulled onto a handset. The full record is `docs/scale-run-2026-09-12-sindh.md`.

We want to be exact about what that was. **It was not your questionnaire.** What
we have is your *description* of it; the content — every question, every skip
rule, every option label — was invented to match the shape. So it says nothing
about your survey and quite a lot about our platform.

What it found, because these are the numbers worth planning against:

| | |
|---|---|
| Import, workbook plus both companion CSVs | **1.0 second** |
| Questions accepted | 2,128 of 2,128 |
| Cells read and accounted for | 50,385, all of them |
| **Errors** | **3** — see §6 |
| Warnings | 0 |
| Publishing the 45,327-row list | 4.9 seconds |
| Downloading it onto a phone | under 8 seconds |
| The form opening on the phone | under half a second |

Three errors in 2,128 questions, and all three are types we have not built a
widget for. Nothing about the size gave this platform any trouble — with one
exception that was ours and is fixed, and one decision in §2 that is now yours.

---

## 1. The three sheets

`survey`, `choices`, `settings` — standard XLSForm. `settings` must carry
`form_title`, `form_id`, `version` and `default_language`.

Labels are per language, `label::English (en)`. Anything after `::` becomes the
language key, so use the same spelling in every column. **The template carries
English, Urdu and Sindhi**, because that is what your questionnaires carry and a
two-language example does not show you what the third column looks like.

---

## 2. Question types we can collect

These ten are what a phone can present today. **The template uses every one of
them**, so the workbook is the reference for the exact spelling — and a test
fails if that ever stops being true.

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

Plus the structural rows: `begin group` / `end group`, `begin repeat` /
`end repeat` (§5), and `calculate`.

### 2.1 `appearance: field-list` — please use it, and here is why

**This is the change most likely to affect how your tool emits, and it is worth
reading even if you skip the rest.**

By default each question gets a screen of its own. `appearance: field-list` on a
`begin group` puts that group's questions **together on one screen**.

```
type          name        label::English (en)      appearance
begin group   screening   Screening                field-list
select_one…   consent     Does the respondent…
integer       visit_number Visit number
text          listed_head_name Head of household
end group
```

The scale run is why we are asking. Your 2,128 questions imported to **2,101
screens** — one tap each, 2,101 times through the questionnaire. Re-imported
with the questions grouped into blocks of six, the same 2,128 questions produce
**469 screens**. Nothing else changed: every question is still asked, both
rosters are intact, the same three errors and no others.

2,101 versus 469 is the difference between a form an enumerator can work
through and one they cannot, and **only you know where the groupings belong** —
they are on the paper original, not in anything you have sent us.

Two honest notes:

- We read `field-list` and `table-list`, and we read them **as of 12 September
  2026** — the column was ignored before that date. If you have already written
  an emitter against the older version of this document, emitting it now is safe
  and does something.
- `table-list` is ODK's field-list plus a tabular layout. We take the grouping;
  the layout is a display hint our format does not carry, and the report says so
  per group rather than dropping the grouping with it.
- Extra tokens are fine — `field-list minimal` groups the questions and reports
  `minimal` as unread. `appearance` on a **question** is still carried and
  unread; nothing varies on it.
- `appearance` on a `begin repeat` is not applied, and the report says why: a
  repeat is already one screen an enumerator enters and leaves (§5).

### 2.2 Types that are in our specification and that a phone cannot yet show

These would reach an enumerator as a question they cannot answer, so **they are
refused** — now on import *and* at publish, which was not true until 12
September 2026. Do not emit them:

`boolean`, `time`, `datetime`, `barcode`, `audio`, `video`, `file`, `drawing`,
`geotrace`, `geoshape`.

`time` is the first candidate for the next version. `boolean` is not a gap in
practice: XLSForm has no boolean of its own, so yes/no arrives as a
`select_one`, which is what the template does.

### 2.3 Types that are not in our specification at all

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

The scale run carried about 1,100 relevance expressions, some reading a question
that was itself conditional. The whole dependency graph recalculates in under
four milliseconds, so there is no reason to hold back on them.

**Operators and functions that survive the import:** `and`, `or`, `not`, the
comparisons, `+ - * div mod`, and `count`, `sum`, `min`, `max`,
`count-selected`, `selected`, `coalesce`, `today`, `now`, `string-length`,
`upper-case`, `lower-case`, `normalize-space`, `concat`, `substr`, `contains`,
`starts-with`, `ends-with`, `regex`, `round`, `int`, `number`, `string`.

Anything else is reported by name and cell rather than silently dropped, which
is why the report is worth reading even when the import succeeds.

`constraint_message::<language>` is worth filling in. A refusal with no message
is a form the enumerator cannot get past and cannot explain.

### 3.1 `default` — this is what your Person Id questions become

A `default` either holds a literal or reads an earlier answer:

```
default:  1                    a literal, typed to match the question
default:  ${head_name}         the answer given earlier in the form
```

Both are in the template. For each Person Id question, tell us which of the two
it is — or that it comes from the **sample**, which is a third thing (a roster's
`bind`) and the one case a workbook cannot express on its own.

---

## 4. External choice lists

`select_one_from_file districts.csv`, with the CSV shipped beside the workbook.
It needs a `name` column and a `label` column; `name` is what is stored and
`label` is what is shown.

**Send the whole file.** Extra columns are not an error — the report says how
many of them the form actually reads (`2/5 columns read`), which is how a
renamed column gets noticed. A file the survey sheet names and we cannot find
**is** an error naming the file, never a question that quietly has no options.

Scale is not a concern here. Your 45,327-row school list published in 4.9
seconds, reached a handset in 23 pages, and applied in under 8 seconds.

---

## 5. Rosters work

A roster is `begin repeat` / `end repeat`. The instance count comes from an
earlier answer:

```
repeat_count:  ${hh_size}
```

…or from a column on the sample row, or — leave `repeat_count` **empty** — from
the enumerator, who keeps adding members until the respondent says stop. All
three import, publish and collect.

**What an enumerator sees.** The roster is one screen showing the members
collected so far. Tapping a member opens their questions, one per screen as
everywhere else; the last one leads back to the list rather than on to the next
member, so "have we got everybody?" is a decision with a place to happen. The
add control is on the list. `dcp-xlsform-roster-example.xlsx` is exactly this
shape.

**Two strings we still owe you**, and the one thing to tell us about them.
Form IR §2.3 defines `addLabel` (what the add control says — "Add another
household member") and `summaryLabel` (what one row of the list says —
`${member_name}, age ${member_age}`). Both are per-form and per-language, so
they belong in your workbook rather than in our client. **Neither is read from a
workbook yet**; until then the add control uses the repeat's `label` and each
row shows its position — 1, 2, 3.

The thing to tell us: **is the name you would put in that row a field you would
mark sensitive?** If it is, we have a decision to make before you meet it rather
than after — a label interpolating a sensitive field is refused at publish
(Form IR §7.1), which would leave you with a roster of numbers.

**What the count does.** A repeat is one screen in the progress indicator,
whatever it holds. A household with six members reads `4 of 12` and still reads
`4 of 12` when a seventh is added — the enumerator gets a separate `member 3 of
6` while they are inside one. A denominator that moved as the roster grew would
be a promise about remaining work that the form then withdrew, and for a roster
whose length only the respondent knows it cannot be predicted by anybody.

**One shape to avoid.** A `begin repeat` inside a `begin group` whose
`appearance` is `field-list` is refused. `field-list` means "show these
questions together on one screen" and a repeat means "this is a separate screen
you enter and leave"; both cannot be true of the same questions, so the refusal
is stating a contradiction rather than choosing a side. A repeat **beside** a
field-list group, or inside a plain group, is fine. Now that §2.1 asks you to
emit `appearance`, this is a shape your tool can actually produce, so the
importer reports it against the row rather than letting it fail later.

**Still not supported: a repeat inside a repeat.** That is a compile error and
stays one until IR v0.2.

---

## 6. What we do not support that your current forms use

The scale run turned this from a list into a measurement. Of 2,128 questions in
an instrument of your shape, **three were refused**:

| Your type | Count | What happened | What to emit |
|---|---|---|---|
| Single Selection | 1,461 | imported | `select_one` |
| Edit Text | 425 | imported | `text` / `integer` / `decimal` |
| **Custom Multiple Selection** | **88** | imported **as a plain `select_multiple`** | see below |
| Person Id | 73 | imported | its underlying type with a `default` — §3.1 |
| Multiple Selection | 65 | imported | `select_multiple` |
| **Input Field** | **5** | imported **as `text`, on our guess** | tell us which type |
| **Custom Single Selection** | **3** | imported **as a plain `select_one`** | see below |
| **Time Picker** | **2** | **REFUSED** | nothing yet; `time` has no widget |
| **Enum Selection** | **2** | imported **as `select_one`, on our guess** | tell us what distinguishes it |
| Date Picker | 2 | imported | `date` |
| **Structure Map** | **1** | **REFUSED** | nothing; not planned for the pilot |
| Note | 1 | imported | `note` |

**The three refusals are not the problem. The 96 silent ones are.**

`Custom Multiple Selection`, `Custom Single Selection`, `Input Field` and `Enum
Selection` — 96 questions between them — imported **cleanly, with no diagnostic
at all**, because we chose what to emit for them. If `Custom` carries any
behaviour beyond the list, those questions arrive stripped of it and **nothing
anywhere says so**. A refusal is safe: you see it and we fix it. A silent guess
is not.

That is why §7 asks for one specific thing rather than a description.

---

## 7. What to send back

**Two things, and the first is the one that matters.**

1. **The section Kotlin for one `Custom Multiple Selection` question.** Not a
   description of what it does — the source. We have asked what "Custom" means
   twice and a sentence has not settled it, because what we need to know is
   whether there is behaviour in the screen that a list cannot carry. One
   section file answers it for all 91 `Custom` questions. If `Input Field` and
   `Enum Selection` live in the same file, send those too.

2. **Can your questionnaire → CSV template tool emit XLSForm?** This is the
   highest-leverage question we have and we have not asked it directly before.
   If it can, then the conversion problem applies only to the questionnaires
   that already exist, and everything you write from now on arrives in a format
   this platform imports in a second. If it cannot, we would like to know what
   stands in the way — it may be smaller than it looks.

And, if you are willing: **one real questionnaire emitted as XLSForm, with its
companion CSVs.** We will run it through the importer and send you the report.
The report names every problem in one pass rather than stopping at the first, so
one round trip should be enough.

---

## 8. What we still owe you

Stated so that none of it arrives as a surprise:

- **`addLabel` and `summaryLabel`** are not read from a workbook (§5). Put them
  in yours anyway; we will read them without you changing anything.
- **`time`** is in our format with no widget on any platform. It is the first
  candidate for the next version, and we have no date.
- **Structure Map** has nothing behind it and is not planned for the pilot.
- **A roster prefilled from the sample** — the third source in §3.1 — is
  expressible in our format and not in a workbook. It needs a conversation, not
  a column.
