#!/usr/bin/env python3
"""A questionnaire the size of RCons's Sindh listing, in our own template's shape.

    python scripts/generate_sindh_scale_form.py
    python scripts/generate_sindh_scale_form.py --out /tmp/sindh

## What this is, and what it is not

`docs/rcons-current-system.md` measures RCons's largest questionnaire — the
Sindh male/female household listing — and publishes its **shape**: 95 sections,
2,128 questions, 7,080 options, a per-type census, three languages, two external
lists of 45,327 and 4,035 rows, and two rosters. What that document does *not*
contain, and what this repository has never held, is the questionnaire itself.
There is no `questions` table here to read.

So this generates an instrument that matches every published number exactly and
invents everything else. **It is not RCons's questionnaire and nothing produced
from it may be described as theirs.** What it is for is the only question a
synthetic form can answer honestly, which is also the question that has never
been asked here: what does this platform do when the form is 700 times the size
of every form it has ever been shown? Every run to date has walked a
three-screen form.

The numbers it reproduces, each from `docs/rcons-current-system.md`:

  §1  95 sections, 2,128 questions, 7,080 options
  §2  three languages (ur/en/si), `list_school` 45,327 rows,
      `list_health_facility` 4,035 rows
  §4  two rosters — one counted from an earlier answer, one the enumerator
      drives, which are two of the three ways §4 says a count is decided
  §5  the type census, question for question:
        Single Selection 1461, Edit Text 425, Custom Multiple Selection 88,
        Person Id 73, Multiple Selection 65, Input Field 5,
        Custom Single Selection 3, Time Picker 2, Enum Selection 2,
        Date Picker 2, Structure Map 1, Note 1

Each of those twelve is emitted as the nearest XLSForm spelling — the one
`docs/xlsform-template.md` §6 tells RCons to emit, including for the three the
platform has no answer for. `Time Picker` goes out as `time` and `Structure
Map` as `geoshape` **on purpose**: both are in Form IR §2.1, neither is
collectable, and a run that quietly substituted `text` for them would be
measuring a form nobody would ever send.

## Where the fidelity stops, stated rather than implied

- **The text is invented.** Section titles, question labels and option labels
  are composed from word pools. The Urdu and Sindhi are real script, because
  RTL and UTF-8 width are part of what is under test, but they are not
  translations of anything.
- **Relevance is invented, and it is the load-bearing invention.** §3 of that
  document, as corrected by `docs/phase3-pilot-scope.md` §12, says RCons's skip
  logic is Urdu prose that a person converts by hand, so there is no corpus of
  conditions to copy. What is generated instead is a *density* — about 55% of
  non-gate questions carry a `relevant` reading an earlier answer, some of them
  two levels deep — chosen to put a realistic dependency graph under the
  topological sort rather than to reproduce any particular question's condition.
- **Constraints are ranges**, standing in for the 34 KB of `plausible_ranges.json`
  §2 names.
- **One choice list per select question**, because `options` is 7,080 rows
  against 1,617 select questions and that is what a table keyed by question
  looks like. A real workbook would share `yes_no` across hundreds of them; this
  one does not, which makes the `choices` sheet the worst case rather than the
  likely one. Said plainly because it is the single assumption most likely to
  move a number in the report.

## Determinism

Byte-identical on every run and every Python version. The PRNG is SplitMix64 in
eight lines for the reason `generate_ucl_datasets.py` gives: `random.choice` is
an implementation that has changed, and a report quoting a checksum has to be
reproducible.
"""

from __future__ import annotations

import argparse
import csv
import pathlib

import openpyxl

# --------------------------------------------------------------------------
# A PRNG that cannot change under us
# --------------------------------------------------------------------------

_MASK = (1 << 64) - 1


class Rng:
    """SplitMix64. Fixed algorithm, fixed output, forever."""

    def __init__(self, seed: int) -> None:
        self._state = seed & _MASK

    def next(self) -> int:
        self._state = (self._state + 0x9E3779B97F4A7C15) & _MASK
        z = self._state
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK
        return z ^ (z >> 31)

    def below(self, n: int) -> int:
        return self.next() % n

    def pick(self, items: list[str]) -> str:
        return items[self.below(len(items))]

    def percent(self, p: int) -> bool:
        return self.below(100) < p


# --------------------------------------------------------------------------
# Vocabulary. Invented, and composed rather than listed, so that 95 sections
# and 2,128 questions do not need 2,223 hand-written strings.
# --------------------------------------------------------------------------

SECTION_DOMAINS = [
    "Identification", "Structure listing", "Household roster", "Dwelling",
    "Water and sanitation", "Energy", "Assets", "Livestock", "Land and tenure",
    "Agriculture", "Migration", "Employment", "Education", "Child health",
    "Maternal health", "Immunisation", "Nutrition", "Food security",
    "Disability", "Mortality", "Fertility", "Marriage", "Birth registration",
    "Social protection", "Remittances", "Credit and savings", "Enterprise",
    "Consumption", "Housing quality", "Sanitation facility", "Handwashing",
    "Mosquito nets", "Chronic illness", "Health facility access",
    "School attendance", "Literacy", "Vocational training", "Media exposure",
    "Decision making", "Time use", "Shocks and coping", "Community services",
    "Transport", "Communication", "Financial inclusion", "Governance",
    "Security", "Environment",
]

SECTION_QUALIFIERS = [
    "", " — male", " — female", " — roster", " — follow-up", " — v2",
    " (listing)", " (screening)", " — head", " — members",
]

QUESTION_STEMS = [
    "Does the household", "How many", "In the last 12 months, did",
    "What is the main", "Who usually", "Has this person ever",
    "During the past week, how often", "What was the",
    "Is there a functioning", "How long does it take to reach",
    "Which of the following", "At what age did", "What is the highest",
    "Was the respondent", "How much was spent on", "Does any member",
    "What is the current", "How many times in the last", "Where does",
    "Why was",
]

QUESTION_TAILS = [
    "own this dwelling", "members aged under five", "any member migrate for work",
    "source of drinking water", "collect the water", "attended school",
    "meals were skipped", "main construction material of the roof",
    "latrine on the premises", "the nearest health facility",
    "applies to this household", "this person first marry",
    "level of education completed", "present at the interview",
    "medicines last month", "work outside the settlement",
    "marital status of this person", "month the household borrowed",
    "this household get its electricity", "this structure not listed earlier",
]

# Urdu and Sindhi are real script. They are not translations — see the module
# docstring. Both are here because the labels have to be RTL and multi-byte.
URDU_WORDS = [
    "گھرانہ", "فرد", "عمر", "تعلیم", "پانی", "بجلی", "مکان", "زمین", "صحت",
    "بچہ", "ماں", "کام", "آمدنی", "خوراک", "سفر", "اسکول", "بیماری", "علاج",
    "شادی", "پیدائش", "سہولت", "ذریعہ", "تعداد", "مہینہ", "سال",
]

SINDHI_WORDS = [
    "گهراڻو", "ماڻهو", "عمر", "تعليم", "پاڻي", "بجلي", "گهر", "زمين", "صحت",
    "ٻار", "ماءُ", "ڪم", "آمدني", "خوراڪ", "سفر", "اسڪول", "بيماري", "علاج",
    "شادي", "ڄمڻ", "سهولت", "ذريعو", "تعداد", "مهينو", "سال",
]

OPTION_LABELS = [
    "Yes", "No", "Do not know", "Refused", "Other", "Always", "Sometimes",
    "Never", "Piped", "Hand pump", "Well", "Tanker", "Pond", "Own", "Rented",
    "Free", "Mud", "Brick", "Concrete", "Wood", "Thatch", "None", "Primary",
    "Middle", "Matric", "Intermediate", "Degree", "Male", "Female",
    "Head", "Spouse", "Son or daughter", "Parent", "Other relative",
    "Not related", "Government", "Private", "NGO", "Employer", "Self",
    "Daily", "Weekly", "Monthly", "Seasonally", "Once", "Twice",
    "Three or more times", "Less than 15 minutes", "15 to 30 minutes",
    "30 to 60 minutes", "More than one hour", "Within the settlement",
    "Another settlement", "Another district", "Another province",
    "Outside Pakistan",
]

# --------------------------------------------------------------------------
# The census, straight out of docs/rcons-current-system.md §5
# --------------------------------------------------------------------------

#: Their type -> (count, the XLSForm spelling docs/xlsform-template.md §6 asks
#: for). The third element is what this generator emits it as internally.
RCONS_CENSUS: list[tuple[str, int, str]] = [
    ("Single Selection", 1461, "select_one"),
    ("Edit Text", 425, "edit_text"),
    ("Custom Multiple Selection", 88, "select_multiple"),
    ("Person Id", 73, "person_id"),
    ("Multiple Selection", 65, "select_multiple"),
    ("Input Field", 5, "text"),
    ("Custom Single Selection", 3, "select_one"),
    ("Time Picker", 2, "time"),
    ("Enum Selection", 2, "select_one"),
    ("Date Picker", 2, "date"),
    ("Structure Map", 1, "geoshape"),
    ("Note", 1, "note"),
]

TOTAL_QUESTIONS = 2128
TOTAL_SECTIONS = 95
TOTAL_OPTIONS = 7080
SCHOOL_ROWS = 45_327
HEALTH_FACILITY_ROWS = 4_035

SURVEY_COLUMNS = [
    "type", "name",
    "label::English (en)", "label::Urdu (ur)", "label::Sindhi (sd)",
    "hint::English (en)", "required", "relevant", "constraint",
    "constraint_message::English (en)", "default", "repeat_count",
]

CHOICES_COLUMNS = [
    "list_name", "name", "label::English (en)", "label::Urdu (ur)",
    "label::Sindhi (sd)",
]


# --------------------------------------------------------------------------
# Planning: how the 2,128 are laid out before a single cell is written
# --------------------------------------------------------------------------


def section_sizes(rng: Rng) -> list[int]:
    """95 section sizes summing to 2,128, uneven on purpose.

    A flat 22.4 per section would make every section the same tree, and the
    console's builder is being asked whether it survives *this* tree. Real
    listing questionnaires have a four-question identification block and a
    ninety-question roster module.
    """
    weights = [3 + (i * 7 % 31) + (12 if i % 9 == 0 else 0) for i in range(TOTAL_SECTIONS)]
    total = sum(weights)
    sizes = [max(3, w * TOTAL_QUESTIONS // total) for w in weights]
    # Settle the remainder deterministically rather than dropping it on the
    # last section, which would give the tree one absurd outlier.
    index = 0
    while sum(sizes) < TOTAL_QUESTIONS:
        sizes[index % TOTAL_SECTIONS] += 1
        index += 1
    while sum(sizes) > TOTAL_QUESTIONS:
        if sizes[index % TOTAL_SECTIONS] > 3:
            sizes[index % TOTAL_SECTIONS] -= 1
        index += 1
    del rng
    return sizes


def option_counts(rng: Rng, lists: int) -> list[int]:
    """`lists` list sizes summing to exactly 7,080.

    The distribution is the one a listing survey has: a great many yes/no/DK
    triples, a long tail of code frames, and a handful of 30-option lists for
    relationship and occupation.
    """
    sizes: list[int] = []
    for _ in range(lists):
        roll = rng.below(100)
        if roll < 42:
            sizes.append(2 + rng.below(2))
        elif roll < 70:
            sizes.append(3 + rng.below(2))
        elif roll < 90:
            sizes.append(5 + rng.below(4))
        elif roll < 98:
            sizes.append(9 + rng.below(7))
        else:
            sizes.append(20 + rng.below(21))
    index = 0
    while sum(sizes) > TOTAL_OPTIONS:
        if sizes[index % lists] > 2:
            sizes[index % lists] -= 1
        index += 1
    while sum(sizes) < TOTAL_OPTIONS:
        sizes[index % lists] += 1
        index += 1
    return sizes


def type_pool(rng: Rng) -> list[str]:
    """2,128 internal type tokens, in the census's exact proportions.

    `edit_text` is split here because §5's "Edit Text 425" is one row covering
    three Form IR dataTypes, and which of the three a question is decides
    whether it gets a range constraint.
    """
    pool: list[str] = []
    for _, count, emitted in RCONS_CENSUS:
        if emitted == "edit_text":
            pool += ["text"] * 191 + ["integer"] * 170 + ["decimal"] * 64
        else:
            pool += [emitted] * count
    assert len(pool) == TOTAL_QUESTIONS, len(pool)
    # Fisher-Yates with our own PRNG.
    for i in range(len(pool) - 1, 0, -1):
        j = rng.below(i + 1)
        pool[i], pool[j] = pool[j], pool[i]
    return pool


# --------------------------------------------------------------------------
# Building
# --------------------------------------------------------------------------


class Builder:
    def __init__(self, rng: Rng) -> None:
        self.rng = rng
        self.survey: list[list[str]] = []
        self.choices: list[list[str]] = []
        self.list_sizes: list[int] = []
        self.list_index = 0
        self.question_number = 0
        #: name -> the first option value, for building a `relevant` that reads it
        self.selects: dict[str, str] = {}
        self.numerics: list[str] = []
        self.texts: list[str] = []
        self.emitted: dict[str, int] = {}
        #: The roster currently open, if any. A repeat's questions are
        #: conditional on each other per instance, so they need their own
        #: scope — a `relevant` reading a question outside the repeat is a
        #: different statement from one reading a sibling inside it.
        self.roster_selects: list[str] = []
        self.roster_numerics: list[str] = []
        self.roster_texts: list[str] = []
        self.roster_gate: str | None = None

    # -- labels ---------------------------------------------------------

    def labels(self, english: str) -> tuple[str, str, str]:
        urdu = " ".join(self.rng.pick(URDU_WORDS) for _ in range(3))
        sindhi = " ".join(self.rng.pick(SINDHI_WORDS) for _ in range(3))
        return english, urdu, sindhi

    def question_label(self) -> str:
        return f"{self.rng.pick(QUESTION_STEMS)} {self.rng.pick(QUESTION_TAILS)}?"

    # -- choices --------------------------------------------------------

    def new_list(self, name: str) -> tuple[str, str]:
        """Write one question's options; return (list_name, first option value)."""
        size = self.list_sizes[self.list_index]
        self.list_index += 1
        list_name = f"opt_{name}"
        for position in range(size):
            label = OPTION_LABELS[(position + self.list_index) % len(OPTION_LABELS)]
            english, urdu, sindhi = self.labels(label)
            self.choices.append([list_name, f"o{position + 1}", english, urdu, sindhi])
        return list_name, "o1"

    # -- rows -----------------------------------------------------------

    def row(self, **cells: str) -> None:
        self.survey.append([cells.get(column, "") for column in SURVEY_COLUMNS])

    def count(self, kind: str) -> None:
        self.emitted[kind] = self.emitted.get(kind, 0) + 1

    def question(
        self,
        kind: str,
        section: int,
        gate: str | None,
        local_selects: list[str],
        local_numerics: list[str],
        local_texts: list[str],
        *,
        relevance_allowed: bool = True,
    ) -> None:
        self.question_number += 1
        name = f"s{section:02d}q{self.question_number:04d}"
        english, urdu, sindhi = self.labels(self.question_label())
        cells: dict[str, str] = {
            "name": name,
            "label::English (en)": english,
            "label::Urdu (ur)": urdu,
            "label::Sindhi (sd)": sindhi,
        }

        if kind == "select_one" or kind == "select_multiple":
            list_name, first = self.new_list(name)
            cells["type"] = f"{kind} {list_name}"
            self.selects[name] = first
            local_selects.append(name)
        elif kind in ("text", "integer", "decimal", "date", "time", "geoshape", "note"):
            cells["type"] = kind
            if kind in ("integer", "decimal"):
                local_numerics.append(name)
                self.numerics.append(name)
            elif kind == "text":
                local_texts.append(name)
                self.texts.append(name)
        elif kind == "person_id":
            # docs/xlsform-template.md §6: a prefilled question of its
            # underlying type, filled from an answer given earlier.
            underlying = "integer" if self.rng.percent(32) else "text"
            cells["type"] = underlying
            source = local_texts or self.texts
            if underlying == "integer":
                source = local_numerics or self.numerics
            if source:
                cells["default"] = f"${{{source[-1]}}}"
        elif kind == "school" or kind == "health_facility":
            cells["type"] = f"select_one_from_file {kind}.csv"
        else:  # pragma: no cover - the pool holds nothing else
            raise AssertionError(kind)
        self.count(kind)

        if self.rng.percent(70):
            cells["required"] = "yes"

        if cells["type"] == "integer":
            cells["constraint"] = f"${{{name}}} >= 0 and ${{{name}}} <= 99"
            cells["constraint_message::English (en)"] = "Enter a whole number from 0 to 99."
        elif cells["type"] == "decimal":
            cells["constraint"] = f"${{{name}}} >= 0 and ${{{name}}} <= 250000"
            cells["constraint_message::English (en)"] = "Enter an amount from 0 to 250000."
        elif cells["type"] == "text" and self.rng.percent(40):
            cells["constraint"] = f"string-length(${{{name}}}) <= 60"
            cells["constraint_message::English (en)"] = "Please keep this under 60 characters."
        elif cells["type"] == "date":
            cells["constraint"] = f"${{{name}}} <= today()"
            cells["constraint_message::English (en)"] = "This cannot be in the future."

        if relevance_allowed and gate is not None and self.rng.percent(55):
            cells["relevant"] = self.relevance(gate, local_selects, local_numerics, name)

        if self.rng.percent(18):
            cells["hint::English (en)"] = "Read the question exactly as written."

        self.row(**cells)

    def open_roster(self, section: int, local_numerics: list[str]) -> None:
        """`begin repeat`, counted from an earlier answer or driven by the enumerator.

        `docs/rcons-current-system.md` §4 lists three ways the count is decided
        and says the third — the enumerator adding until the respondent stops —
        is the common case for a household member roster. Both are here because
        they are different screen plans, not different cell values.
        """
        name = f"roster{section:02d}"
        english, urdu, sindhi = self.labels("Household members")
        cells = {
            "type": "begin repeat", "name": name,
            "label::English (en)": english, "label::Urdu (ur)": urdu,
            "label::Sindhi (sd)": sindhi,
        }
        if section == 2 and local_numerics:
            cells["repeat_count"] = f"${{{local_numerics[0]}}}"
        self.row(**cells)
        self.roster_selects = []
        self.roster_numerics = []
        self.roster_texts = []
        self.roster_gate = None

    def relevance(
        self, gate: str, local_selects: list[str], local_numerics: list[str], name: str
    ) -> str:
        """A condition reading an answer given earlier in this section.

        Three shapes and no more, because the point of the density is the
        dependency graph rather than expressive range: a gate read directly, a
        second level that reads another conditional question, and a conjunction
        that puts two fields in one node's dependency set.
        """
        others = [s for s in local_selects if s != name]
        roll = self.rng.below(100)
        if roll < 55 or not others:
            return f"${{{gate}}} = '{self.selects[gate]}'"
        if roll < 85:
            other = others[self.rng.below(len(others))]
            return f"${{{other}}} = '{self.selects[other]}'"
        other = others[self.rng.below(len(others))]
        if local_numerics:
            number = local_numerics[self.rng.below(len(local_numerics))]
            return f"${{{gate}}} = '{self.selects[gate]}' and ${{{number}}} > 0"
        return f"${{{gate}}} = '{self.selects[gate]}' and ${{{other}}} != '{self.selects[other]}'"


def build(rng: Rng) -> Builder:
    builder = Builder(rng)
    pool = type_pool(rng)

    # The two external lists replace two Single Selections, and the two rosters
    # are carved out of two sections. Both are §2/§4 facts about the real
    # instrument, and both have to come out of the 2,128 rather than be added
    # to it.
    for wanted, external in ((311, "school"), (1904, "health_facility")):
        slot = next(i for i in range(wanted, len(pool)) if pool[i] == "select_one")
        pool[slot] = external

    sizes = section_sizes(rng)
    # One inline list per select question, which is what `options` being keyed
    # by question means. Counted before anything is written because the sizes
    # have to sum to exactly 7,080.
    inline_lists = sum(1 for t in pool if t in ("select_one", "select_multiple"))
    # Every section's first question is a gate, and a gate is a select_one:
    # those are already in `pool`, so nothing is added — but a select_one that
    # lands in position 0 of a section keeps its list either way.
    builder.list_sizes = option_counts(rng, inline_lists)

    roster_sections = {2, 47}  # "Household roster — male" / "— female"
    cursor = 0
    for section in range(TOTAL_SECTIONS):
        domain = SECTION_DOMAINS[section % len(SECTION_DOMAINS)]
        qualifier = SECTION_QUALIFIERS[section % len(SECTION_QUALIFIERS)]
        title = f"{section + 1:02d}. {domain}{qualifier}"
        english, urdu, sindhi = builder.labels(title)
        group = f"sec{section + 1:02d}"
        builder.row(
            **{
                "type": "begin group", "name": group,
                "label::English (en)": english, "label::Urdu (ur)": urdu,
                "label::Sindhi (sd)": sindhi,
            }
        )

        size = sizes[section]
        types = pool[cursor : cursor + size]
        cursor += size
        # The gate: the section's first question must be a select_one so that
        # everything after it has something to be conditional on. Swap the
        # first select_one in the section into position 0 rather than adding
        # one, so the census is untouched.
        for position, kind in enumerate(types):
            if kind == "select_one":
                types[0], types[position] = types[position], types[0]
                break

        local_selects: list[str] = []
        local_numerics: list[str] = []
        local_texts: list[str] = []
        gate: str | None = None

        roster_at = -1
        roster_size = 0
        if section in roster_sections:
            roster_at = min(6, size // 3)
            roster_size = min(16, size - roster_at - 1)

        for position, kind in enumerate(types):
            if position == roster_at and roster_size > 0:
                builder.open_roster(section, local_numerics)
                for inner in types[position : position + roster_size]:
                    builder.question(
                        inner, section, builder.roster_gate, builder.roster_selects,
                        builder.roster_numerics, builder.roster_texts,
                    )
                    if builder.roster_gate is None and builder.roster_selects:
                        builder.roster_gate = builder.roster_selects[0]
                builder.row(**{"type": "end repeat"})
            if roster_at <= position < roster_at + roster_size and roster_size > 0:
                continue
            builder.question(kind, section, gate, local_selects, local_numerics, local_texts)
            if gate is None and local_selects:
                gate = local_selects[0]

        builder.row(**{"type": "end group"})

    return builder


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------


def write_workbook(builder: Builder, path: pathlib.Path) -> None:
    workbook = openpyxl.Workbook(write_only=True)
    survey = workbook.create_sheet("survey")
    survey.append(SURVEY_COLUMNS)
    for row in builder.survey:
        survey.append(row)
    choices = workbook.create_sheet("choices")
    choices.append(CHOICES_COLUMNS)
    for row in builder.choices:
        choices.append(row)
    settings = workbook.create_sheet("settings")
    settings.append(["form_title", "form_id", "version", "default_language"])
    settings.append(
        [
            "Sindh household listing (scale probe, synthetic)",
            "sindh_listing_scale",
            "1",
            "English (en)",
        ]
    )
    workbook.save(path)


def write_dataset(path: pathlib.Path, rows: int, prefix: str, rng: Rng) -> None:
    """A companion list with more columns than the form reads (Form IR §3.1)."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["name", "label", "district", "tehsil", "status"])
        for index in range(rows):
            key = f"{prefix}{index + 1:06d}"
            writer.writerow(
                [
                    key,
                    f"{rng.pick(OPTION_LABELS)} {prefix.upper()} {index + 1}",
                    f"D{index % 30 + 1:02d}",
                    f"T{index % 137 + 1:03d}",
                    "functional" if index % 11 else "non-functional",
                ]
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1]
        / "backend/tests/fixtures/xlsform/sindh-scale",
        help="directory to write the workbook and its two CSVs into",
    )
    parser.add_argument("--seed", type=int, default=20260912, help="PRNG seed")
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)

    builder = build(Rng(arguments.seed))

    workbook_path = arguments.out / "sindh-listing-scale.xlsx"
    write_workbook(builder, workbook_path)
    write_dataset(arguments.out / "school.csv", SCHOOL_ROWS, "sch", Rng(arguments.seed + 1))
    write_dataset(
        arguments.out / "health_facility.csv", HEALTH_FACILITY_ROWS, "hf",
        Rng(arguments.seed + 2),
    )

    questions = sum(
        1
        for row in builder.survey
        if row[0] and not row[0].startswith(("begin ", "end "))
    )
    print(f"{workbook_path}")
    print(f"  survey rows   {len(builder.survey):>7,}")
    print(f"  questions     {questions:>7,}  (target {TOTAL_QUESTIONS:,})")
    print(f"  sections      {TOTAL_SECTIONS:>7,}")
    print(f"  choice rows   {len(builder.choices):>7,}  (target {TOTAL_OPTIONS:,})")
    print(f"  choice lists  {builder.list_index:>7,}")
    for kind, count in sorted(builder.emitted.items()):
        print(f"    {kind:<18} {count:>6,}")
    print(f"  school.csv          {SCHOOL_ROWS:>7,} rows")
    print(f"  health_facility.csv {HEALTH_FACILITY_ROWS:>7,} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
