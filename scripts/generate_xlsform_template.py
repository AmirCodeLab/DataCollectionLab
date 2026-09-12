#!/usr/bin/env python3
"""The XLSForm pack we hand to a partner, built from one source.

    python scripts/generate_xlsform_template.py
    python scripts/import_xlsform.py docs/xlsform-template/dcp-xlsform-template.xlsx

Writes `docs/xlsform-template/`: two workbooks and the companion CSV one of them
names. **These are committed**, unlike the other generated fixtures in this
repository, because they are the artefact somebody is sent — but they are
generated anyway, and the reason is a wart the pack actually had.

`dcp-xlsform-roster-example.xlsx` was hand-edited in September 2026 while
rosters were refused. When the refusal lifted, `docs/xlsform-template.md` §5 was
updated and the workbook was not: its title still read "(not importable yet)"
and its first row still said "This form is REFUSED by the importer today", while
the importer reported 0 errors and 0 warnings on it. A partner opening the file
would have read the opposite of the documentation, and the documentation is the
thing nobody opens first.

A workbook whose text is generated from a script beside the doc cannot drift
that way on its own. `backend/tests/test_xlsform_template_pack.py` is what makes
that true: it regenerates in memory, compares against what is committed, and
imports both.

Every question type a client can collect appears exactly once in the template,
so it is the reference for the exact spelling. Three languages, because RCons's
questionnaires carry Urdu and Sindhi beside English and a two-language example
does not show what a third column looks like.
"""

from __future__ import annotations

import argparse
import csv
import pathlib

import openpyxl

SURVEY_COLUMNS = [
    "type",
    "name",
    "label::English (en)",
    "label::Urdu (ur)",
    "label::Sindhi (sd)",
    "hint::English (en)",
    "required",
    "relevant",
    "constraint",
    "constraint_message::English (en)",
    "default",
    "appearance",
    "calculation",
]

CHOICES_COLUMNS = [
    "list_name",
    "name",
    "label::English (en)",
    "label::Urdu (ur)",
    "label::Sindhi (sd)",
]

DISTRICTS = [
    ("sk01", "Sukkur City"),
    ("sk02", "Rohri"),
    ("sk03", "Pano Aqil"),
    ("lk01", "Larkana"),
    ("lk02", "Ratodero"),
    ("kh01", "Khairpur"),
    ("kh02", "Kot Diji"),
]


def _row(**cells: str) -> list[str]:
    return [cells.get(column, "") for column in SURVEY_COLUMNS]


# --------------------------------------------------------------------------
# The template: every collectable type once
# --------------------------------------------------------------------------

TEMPLATE_SURVEY = [
    _row(type="begin group", name="household", **{
        "label::English (en)": "Household",
        "label::Urdu (ur)": "گھرانہ",
        "label::Sindhi (sd)": "گهراڻو",
    }),
    _row(type="note", name="intro", **{
        "label::English (en)": "This block shows every question type DCP can collect today.",
        "label::Urdu (ur)": "یہ فارم ہر وہ سوال دکھاتا ہے جو DCP جمع کر سکتا ہے۔",
        "label::Sindhi (sd)": "هي فارم هر اهو سوال ڏيکاري ٿو جيڪو DCP گڏ ڪري سگهي ٿو.",
    }),
    _row(type="text", name="head_name", required="yes", **{
        "label::English (en)": "Name of household head",
        "label::Urdu (ur)": "گھر کے سربراہ کا نام",
        "label::Sindhi (sd)": "گهر جي سربراهه جو نالو",
        "hint::English (en)": "Free text.",
        "constraint": "string-length(${head_name}) <= 60",
        "constraint_message::English (en)": "Please keep the name under 60 characters.",
    }),
    _row(type="integer", name="hh_size", required="yes", **{
        "label::English (en)": "How many people live here?",
        "label::Urdu (ur)": "یہاں کتنے افراد رہتے ہیں؟",
        "label::Sindhi (sd)": "هتي ڪيترا ماڻهو رهن ٿا؟",
        "hint::English (en)": "Whole number. Drives the roster in the other workbook.",
        "constraint": "${hh_size} > 0 and ${hh_size} <= 30",
        "constraint_message::English (en)": "A household must have between 1 and 30 members.",
    }),
    _row(type="decimal", name="monthly_income", **{
        "label::English (en)": "Total monthly income (PKR)",
        "label::Urdu (ur)": "ماہانہ آمدنی",
        "label::Sindhi (sd)": "مهيني جي آمدني",
        "hint::English (en)": "Decimals allowed.",
        "constraint": "${monthly_income} >= 0",
        "constraint_message::English (en)": "Income cannot be negative.",
    }),
    _row(type="date", name="interview_date", required="yes", **{
        "label::English (en)": "Date of interview",
        "label::Urdu (ur)": "انٹرویو کی تاریخ",
        "label::Sindhi (sd)": "انٽرويو جي تاريخ",
        "constraint": "${interview_date} <= today()",
        "constraint_message::English (en)": "The interview cannot be in the future.",
    }),
    _row(type="select_one yes_no", name="owns_land", required="yes", **{
        "label::English (en)": "Does this household own land?",
        "label::Urdu (ur)": "کیا یہ گھرانہ زمین کا مالک ہے؟",
        "label::Sindhi (sd)": "ڇا هي گهراڻو زمين جو مالڪ آهي؟",
        "hint::English (en)": "Single selection from the choices sheet.",
    }),
    _row(type="decimal", name="land_acres", required="yes", **{
        "label::English (en)": "How many acres?",
        "label::Urdu (ur)": "کتنے ایکڑ؟",
        "label::Sindhi (sd)": "ڪيترا ايڪڙ؟",
        "hint::English (en)": "Only asked when the answer above is yes — relevance, not a skip.",
        "relevant": "${owns_land} = 'yes'",
        "constraint": "${land_acres} > 0",
        "constraint_message::English (en)": "Enter an area greater than zero.",
    }),
    _row(type="select_multiple crops", name="crops_grown", **{
        "label::English (en)": "Which crops are grown?",
        "label::Urdu (ur)": "کون سی فصلیں اگائی جاتی ہیں؟",
        "label::Sindhi (sd)": "ڪهڙا فصل پوکيا وڃن ٿا؟",
        "hint::English (en)": "Multiple selection.",
        "relevant": "${owns_land} = 'yes'",
        "constraint": "count-selected(${crops_grown}) <= 4",
        "constraint_message::English (en)": "Choose at most four crops.",
    }),
    _row(type="select_one_from_file districts.csv", name="district", required="yes", **{
        "label::English (en)": "District",
        "label::Urdu (ur)": "ضلع",
        "label::Sindhi (sd)": "ضلعو",
        "hint::English (en)": "An external list. The CSV ships beside this workbook.",
    }),
    _row(type="image", name="house_photo", **{
        "label::English (en)": "Photograph of the dwelling",
        "label::Urdu (ur)": "مکان کی تصویر",
        "label::Sindhi (sd)": "گهر جي تصوير",
    }),
    _row(type="geopoint", name="dwelling_location", **{
        "label::English (en)": "Location of the dwelling",
        "label::Urdu (ur)": "مکان کا مقام",
        "label::Sindhi (sd)": "گهر جو هنڌ",
    }),
    _row(type="signature", name="respondent_signature", **{
        "label::English (en)": "Respondent's signature",
        "label::Urdu (ur)": "جواب دہندہ کے دستخط",
        "label::Sindhi (sd)": "جواب ڏيندڙ جا صحيح",
    }),
    _row(type="calculate", name="income_per_head",
         calculation="${monthly_income} div ${hh_size}"),
    _row(type="end group"),
    # --- the field-list block ------------------------------------------------
    # Read as of 12 September 2026. It is in the template rather than described
    # in prose because the template is what a tool is written against, and a
    # feature only the documentation mentions is one only the documentation has.
    _row(type="begin group", name="screening", appearance="field-list", **{
        "label::English (en)": "Screening — these three share one screen",
        "label::Urdu (ur)": "ابتدائی سوالات",
        "label::Sindhi (sd)": "ابتدائي سوال",
    }),
    _row(type="select_one yes_no", name="consent", required="yes", **{
        "label::English (en)": "Does the respondent consent?",
        "label::Urdu (ur)": "کیا جواب دہندہ رضامند ہے؟",
        "label::Sindhi (sd)": "ڇا جواب ڏيندڙ راضي آهي؟",
    }),
    _row(type="integer", name="visit_number", default="1", **{
        "label::English (en)": "Visit number",
        "label::Urdu (ur)": "دورے کا نمبر",
        "label::Sindhi (sd)": "دوري جو نمبر",
        "hint::English (en)": "A literal `default`, typed to match the question.",
    }),
    _row(type="text", name="listed_head_name", **{
        "label::English (en)": "Head of household (prefilled)",
        "label::Urdu (ur)": "گھر کا سربراہ",
        "label::Sindhi (sd)": "گهر جو سربراهه",
        "hint::English (en)": "A `default` that reads an earlier answer — this is what "
        "your Person Id questions become.",
        "default": "${head_name}",
    }),
    _row(type="end group"),
]

TEMPLATE_CHOICES = [
    ["yes_no", "yes", "Yes", "ہاں", "ها"],
    ["yes_no", "no", "No", "نہیں", "نه"],
    ["crops", "wheat", "Wheat", "گندم", "ڪڻڪ"],
    ["crops", "rice", "Rice", "چاول", "چانور"],
    ["crops", "cotton", "Cotton", "کپاس", "ڪپهه"],
    ["crops", "sugarcane", "Sugarcane", "گنا", "ڪمند"],
]

# --------------------------------------------------------------------------
# The roster example
# --------------------------------------------------------------------------

ROSTER_COLUMNS = SURVEY_COLUMNS + ["repeat_count"]


def _roster_row(**cells: str) -> list[str]:
    return [cells.get(column, "") for column in ROSTER_COLUMNS]


ROSTER_SURVEY = [
    _roster_row(type="note", name="roster_intro", **{
        "label::English (en)": "A roster. This workbook imports with 0 errors and 0 "
        "warnings — see docs/xlsform-template.md section 5 for what an enumerator sees.",
        "label::Urdu (ur)": "یہ فارم گھر کے افراد کی فہرست بناتا ہے۔",
        "label::Sindhi (sd)": "هي فارم گهر جي ڀاتين جي فهرست ٺاهي ٿو.",
    }),
    _roster_row(type="integer", name="hh_size", required="yes", **{
        "label::English (en)": "How many people live here?",
        "label::Urdu (ur)": "یہاں کتنے افراد رہتے ہیں؟",
        "label::Sindhi (sd)": "هتي ڪيترا ماڻهو رهن ٿا؟",
        "hint::English (en)": "Drives the roster below.",
        "constraint": "${hh_size} > 0 and ${hh_size} <= 30",
        "constraint_message::English (en)": "A household must have between 1 and 30 members.",
    }),
    _roster_row(type="select_one_from_file districts.csv", name="district", required="yes", **{
        "label::English (en)": "District",
        "label::Urdu (ur)": "ضلع",
        "label::Sindhi (sd)": "ضلعو",
    }),
    _roster_row(type="begin repeat", name="members", repeat_count="${hh_size}", **{
        "label::English (en)": "Household members",
        "label::Urdu (ur)": "گھر کے افراد",
        "label::Sindhi (sd)": "گهر جا ڀاتي",
        # No `hint` here: the importer takes hints on questions and not on
        # containers, and a warning in the pack we send is a warning a partner
        # reasonably reads as "this template does not import cleanly". What the
        # hint said — leave `repeat_count` empty and the enumerator keeps adding
        # members — is docs/xlsform-template.md §5, which is where guidance
        # about the shape belongs anyway.
    }),
    _roster_row(type="text", name="member_name", required="yes", **{
        "label::English (en)": "Member's name",
        "label::Urdu (ur)": "فرد کا نام",
        "label::Sindhi (sd)": "ڀاتي جو نالو",
    }),
    _roster_row(type="integer", name="member_age", required="yes", **{
        "label::English (en)": "Age",
        "label::Urdu (ur)": "عمر",
        "label::Sindhi (sd)": "عمر",
        "constraint": "${member_age} >= 0 and ${member_age} < 120",
        "constraint_message::English (en)": "Age must be between 0 and 119.",
    }),
    _roster_row(type="select_one relation", name="member_relation", required="yes", **{
        "label::English (en)": "Relation to head",
        "label::Urdu (ur)": "سربراہ سے رشتہ",
        "label::Sindhi (sd)": "سربراهه سان رشتو",
    }),
    _roster_row(type="select_one yes_no", name="member_in_school", **{
        "label::English (en)": "Attends school?",
        "label::Urdu (ur)": "کیا اسکول جاتا ہے؟",
        "label::Sindhi (sd)": "ڇا اسڪول وڃي ٿو؟",
        "hint::English (en)": "Relevance inside a repeat is evaluated per instance.",
        "relevant": "${member_age} >= 5 and ${member_age} <= 18",
    }),
    _roster_row(type="end repeat"),
]

ROSTER_CHOICES = [
    ["yes_no", "yes", "Yes", "ہاں", "ها"],
    ["yes_no", "no", "No", "نہیں", "نه"],
    ["relation", "head", "Head", "سربراہ", "سربراهه"],
    ["relation", "spouse", "Spouse", "شریک حیات", "زال يا مڙس"],
    ["relation", "child", "Child", "بچہ", "ٻار"],
    ["relation", "other", "Other relative", "دیگر رشتہ دار", "ٻيو مائٽ"],
]


def _build(
    columns: list[str],
    survey: list[list[str]],
    choices: list[list[str]],
    title: str,
    form_id: str,
) -> openpyxl.Workbook:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    sheet.title = "survey"
    sheet.append(columns)
    for row in survey:
        sheet.append(row)
    choice_sheet = book.create_sheet("choices")
    choice_sheet.append(CHOICES_COLUMNS)
    for row in choices:
        choice_sheet.append(row)
    settings = book.create_sheet("settings")
    settings.append(["form_title", "form_id", "version", "default_language"])
    settings.append([title, form_id, "1", "English (en)"])
    return book


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1] / "docs/xlsform-template",
        help="directory to write the pack into",
    )
    arguments = parser.parse_args()
    arguments.out.mkdir(parents=True, exist_ok=True)

    _build(
        SURVEY_COLUMNS, TEMPLATE_SURVEY, TEMPLATE_CHOICES,
        "DCP XLSForm template", "dcp_template",
    ).save(arguments.out / "dcp-xlsform-template.xlsx")

    _build(
        ROSTER_COLUMNS, ROSTER_SURVEY, ROSTER_CHOICES,
        "DCP roster example", "dcp_roster_example",
    ).save(arguments.out / "dcp-xlsform-roster-example.xlsx")

    # `\n`, not csv's RFC 4180 default of `\r\n`: this file is committed, git
    # normalises line endings on the way in, and the pack test compares the
    # generator's output against what is on disk. CRLF here means that test
    # passes on the machine that wrote it and fails on the next clone.
    with (arguments.out / "districts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["name", "label"])
        writer.writerows(DISTRICTS)

    print(f"{arguments.out}")
    print(f"  dcp-xlsform-template.xlsx        {len(TEMPLATE_SURVEY):>3} survey rows")
    print(f"  dcp-xlsform-roster-example.xlsx  {len(ROSTER_SURVEY):>3} survey rows")
    print(f"  districts.csv                    {len(DISTRICTS):>3} rows")
    print("\nRun the importer over both before sending them anywhere.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
