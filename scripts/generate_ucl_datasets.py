#!/usr/bin/env python3
"""The UCL biomass form's five companion CSVs — generated, and adversarial.

    python scripts/generate_ucl_datasets.py
    python scripts/generate_ucl_datasets.py --out /tmp/ucl --villages 2000

## Why these are generated rather than committed

`ucl-biomass.xlsx` is a real third-party form (pyxform's
`UCL_Biomass_Plot_Form.xlsx`) and it names five files:

    UCL_regions.csv  UCL_districts.csv  UCL_villages.csv
    ULC_Biomass_Plots.csv  species_names.csv

**None of them exists anywhere.** XLSForm companion files ship beside the
workbook and are not part of it, so no corpus carries them — pyxform's fixture
directory has the .xlsx and nothing else. There is no honest way to obtain
UCL's actual data, and there is no point pretending otherwise: what matters is
whether this pipeline survives data *shaped like* theirs.

So these are synthetic, and the whole design goal is that they be **hostile**
in exactly the ways real Tanzanian administrative data is hostile. A fixture
written to please the importer proves only that the importer handles what its
author already thought of, which is the criticism the whole coverage-ledger
design is built around. Every property below is here because it is real:

  scale             ~25 regions, ~180 districts, tens of thousands of villages.
                    Tanzania's actual shape. Scale is not decoration: it is what
                    decides whether per-keystroke filtering is viable (§12) and
                    what the first-sync measurement is measuring
  diacritics        Swahili orthography, plus the ŋ and ' that appear in
                    Sukuma and Maasai place names, in UTF-8
  repeated names    "Mtakuja" is a village in nine districts. A name is not an
                    identity and a list that assumes it is will merge them
  embedded commas   "Dar es Salaam, Ilala" and names carrying a quote. RFC 4180
                    quoting, which is where a naive split(",") stops working
  blank cells       whitespace-only, and empty, in columns the form does not use
  extra columns     more columns than the form reads, which is the whole reason
                    a delta compares the projection and not the row hash
  confusable keys   keys differing only by case or by surrounding whitespace
                    (§3.1) — the case the platform reports and refuses to merge

## Determinism

Byte-identical on every run and every Python version, because the report and
the checksums quoted in it have to be reproducible. That rules out `random`,
whose *algorithm* is stable but whose `choice`/`sample` implementations have
changed; the PRNG here is eight lines of SplitMix64 and cannot drift.

Nothing here is UCL's data. Anything published from it must say so — see
`backend/tests/fixtures/xlsform/PROVENANCE.md`.
"""

from __future__ import annotations

import argparse
import csv
import pathlib

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

    def chance(self, one_in: int) -> bool:
        return self.below(one_in) == 0


# --------------------------------------------------------------------------
# Tanzanian-shaped vocabulary
# --------------------------------------------------------------------------

REGIONS = [
    "Arusha", "Dar es Salaam", "Dodoma", "Geita", "Iringa", "Kagera", "Katavi",
    "Kigoma", "Kilimanjaro", "Lindi", "Manyara", "Mara", "Mbeya", "Morogoro",
    "Mtwara", "Mwanza", "Njombe", "Pwani", "Rukwa", "Ruvuma", "Shinyanga",
    "Simiyu", "Singida", "Songwe", "Tabora", "Tanga",
]

#: Word stems that really do recur across districts. The repetition is the
#: point: a village name is not a key, and a pipeline that assumes it is will
#: merge nine different Mtakujas into one.
VILLAGE_STEMS = [
    "Mtakuja", "Mbuyuni", "Kibaoni", "Msufini", "Mlimani", "Majengo", "Bwawani",
    "Chekereni", "Kwa Mrefu", "Mji Mpya", "Nyamburi", "Kisiwani", "Mabatini",
    "Ilula", "Mbezi", "Kongowe", "Ngerengere", "Mtoni", "Sokoni", "Shuleni",
    "Mnadani", "Kikwe", "Mererani", "Uhuru", "Kanisani", "Mwembeni", "Bomani",
    "Ngo'mbeni", "Nyaŋʼanyi", "Mahakamani", "Bondeni", "Kilimani", "Mtakatifu",
]

VILLAGE_SUFFIXES = ["", "", "", " Juu", " Chini", " A", " B", " Kati", " Mpya", " Kaskazini"]

DISTRICT_SUFFIXES = ["Mjini", "Vijijini", "Rural", "Urban", "DC", "MC"]

#: Real Miombo woodland genera. Latin names have no language, which is why
#: species_names.csv gets a plain `label` column and the rest get `label::…`.
SPECIES = [
    ("Brachystegia spiciformis", "Miombo"),
    ("Julbernardia globiflora", "Mtundu"),
    ("Pterocarpus angolensis", "Mninga"),
    ("Afzelia quanzensis", "Mkongo"),
    ("Dalbergia melanoxylon", "Mpingo"),
    ("Combretum molle", "Mlama"),
    ("Terminalia sericea", "Mpululu"),
    ("Acacia polyacantha", "Mgunga"),
    ("Albizia harveyi", "Mtanga"),
    ("Sclerocarya birrea", "Mng'ongo"),
    ("Adansonia digitata", "Mbuyu"),
    ("Diospyros mespiliformis", "Mgiriti"),
    ("Bridelia micrantha", "Mkarati"),
    ("Syzygium guineense", "Mzambarau mwitu"),
    ("Parinari curatellifolia", "Mbula"),
    ("Uapaca kirkiana", "Mkusu"),
    ("Ficus sycomorus", "Mkuyu"),
    ("Khaya anthotheca", "Mkangazi"),
    ("Milicia excelsa", "Mvule"),
    ("Senna siamea", "Mjohoro"),
]

PHASES = ["2022", "2023", "2024", "2025", "2026", "2027", "2028"]


def _write(path: pathlib.Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    """One CSV, quoted per RFC 4180, LF endings, UTF-8 without a BOM."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build(villages_wanted: int, seed: int) -> dict[str, tuple[list[str], list[dict[str, str]]]]:
    rng = Rng(seed)
    files: dict[str, tuple[list[str], list[dict[str, str]]]] = {}

    # -- regions ------------------------------------------------------------
    #
    # `zone` and `population` are columns the form never reads. They exist so
    # that "a column no form references changed" is a case the delta mechanism
    # can actually be tested against (item 4 part 5), rather than a hypothesis.
    region_columns = [
        "name", "label::Swahili (sw)", "label::English (en)", "zone", "population",
    ]
    region_rows: list[dict[str, str]] = []
    region_ids: list[str] = []
    for index, region in enumerate(REGIONS, start=1):
        code = f"TZ{index:02d}"
        region_ids.append(code)
        region_rows.append(
            {
                "name": code,
                "label::Swahili (sw)": f"Mkoa wa {region}",
                "label::English (en)": region,
                "zone": ["Kaskazini", "Kati", "Magharibi", "Kusini", "Mashariki"][index % 5],
                # Whitespace-only in a column nothing reads: it must survive the
                # round trip without being confused for a missing key.
                "population": "   " if rng.chance(9) else str(400_000 + rng.below(4_000_000)),
            }
        )
    files["UCL_regions.csv"] = (region_columns, region_rows)

    # -- districts ----------------------------------------------------------
    district_columns = [
        "name", "label::Swahili (sw)", "label::English (en)", "region_id", "council_type",
    ]
    district_rows: list[dict[str, str]] = []
    districts: list[tuple[str, str]] = []  # (district_id, region_id)
    counter = 0
    for index, region in enumerate(REGIONS, start=1):
        region_code = f"TZ{index:02d}"
        for _ in range(5 + rng.below(4)):
            counter += 1
            code = f"D{counter:04d}"
            suffix = rng.pick(DISTRICT_SUFFIXES)
            # A comma inside a value. The commonest real one is exactly this:
            # a council named for the region it sits in.
            english = (
                f"{region}, {suffix}" if rng.chance(11) else f"{region} {suffix}"
            )
            district_rows.append(
                {
                    "name": code,
                    "label::Swahili (sw)": f"Wilaya ya {region} {suffix}",
                    "label::English (en)": english,
                    "region_id": region_code,
                    "council_type": suffix,
                }
            )
            districts.append((code, region_code))
    files["UCL_districts.csv"] = (district_columns, district_rows)

    # -- villages -----------------------------------------------------------
    #
    # The big one, and the one every measurement in item 4 is about.
    village_columns = [
        "name",
        "label::Swahili (sw)",
        "label::English (en)",
        "district_id",
        "region_id",
        "ward",
        "households",
        "notes",
    ]
    village_rows: list[dict[str, str]] = []
    villages: list[tuple[str, str]] = []  # (village_id, district_id)
    per_district = max(1, villages_wanted // max(1, len(districts)))
    number = 0
    for district_code, region_code in districts:
        for _ in range(per_district + rng.below(3) - 1):
            number += 1
            code = f"V{number:06d}"
            stem = rng.pick(VILLAGE_STEMS)
            display = stem + rng.pick(VILLAGE_SUFFIXES)
            village_rows.append(
                {
                    "name": code,
                    "label::Swahili (sw)": display,
                    # A name carrying an apostrophe, which is both real Swahili
                    # orthography and the character that breaks a naive
                    # quoting implementation.
                    "label::English (en)": (
                        f'"{display}" settlement' if rng.chance(23) else display
                    ),
                    "district_id": district_code,
                    "region_id": region_code,
                    "ward": f"Kata ya {rng.pick(VILLAGE_STEMS)}",
                    "households": "" if rng.chance(13) else str(20 + rng.below(900)),
                    "notes": "",
                }
            )
            villages.append((code, district_code))
    files["UCL_villages.csv"] = (village_columns, village_rows)

    # -- plots --------------------------------------------------------------
    #
    # Keyed on a human-typed plot number rather than a generated id, which is
    # what makes it the natural home for the §3.1 confusable-key case: the same
    # plot entered twice, once with a trailing space and once in a different
    # case. They are DIFFERENT rows and the platform says so rather than
    # merging them.
    plot_columns = ["name", "label", "village", "plant_phase", "area_ha", "surveyed_by"]
    plot_rows: list[dict[str, str]] = []
    seen_plot_keys: set[str] = set()
    for index, (village_code, _) in enumerate(villages):
        if not rng.chance(4):
            continue
        phase = rng.pick(PHASES)
        key = f"PLT-{index:05d}-{phase}"
        plot_rows.append(
            {
                "name": key,
                "label": f"Plot {key}",
                "village": village_code,
                "plant_phase": phase,
                "area_ha": f"{(rng.below(400) + 25) / 100:.2f}",
                "surveyed_by": rng.pick(["Aloyce", "Andrea", "  ", ""]),
            }
        )
        seen_plot_keys.add(key)

    # Deliberate §3.1 cases, planted rather than hoped for: a trailing space and
    # a case change on keys that already exist. Both must survive as separate
    # rows and both must be reported.
    for original in sorted(seen_plot_keys)[:3]:
        plot_rows.append(
            {
                "name": original + " ",
                "label": f"Plot {original} (re-entered)",
                "village": villages[0][0],
                "plant_phase": original.rsplit("-", 1)[1],
                "area_ha": "1.00",
                "surveyed_by": "Aloyce",
            }
        )
    for original in sorted(seen_plot_keys)[3:5]:
        plot_rows.append(
            {
                "name": original.lower(),
                "label": f"Plot {original} (lower case)",
                "village": villages[0][0],
                "plant_phase": original.rsplit("-", 1)[1],
                "area_ha": "1.00",
                "surveyed_by": "Andrea",
            }
        )
    files["ULC_Biomass_Plots.csv"] = (plot_columns, plot_rows)

    # -- species ------------------------------------------------------------
    #
    # A plain `label`, no language suffix: a Latin binomial is not English. The
    # importer has to handle both shapes, and this is the one that proves it.
    species_columns = ["name", "label", "swahili_name", "family", "wood_density"]
    species_rows: list[dict[str, str]] = []
    for index, (latin, swahili) in enumerate(SPECIES, start=1):
        species_rows.append(
            {
                "name": f"SP{index:03d}",
                "label": latin,
                "swahili_name": swahili,
                "family": "Fabaceae" if index % 3 else "Combretaceae",
                "wood_density": f"0.{500 + rng.below(300)}",
            }
        )
    # `other`, which the form's `${latin_name_id}='other'` relevant depends on.
    # Without it that whole branch is unreachable, and it is exactly the kind of
    # row a generated fixture forgets.
    species_rows.append(
        {
            "name": "other",
            "label": "Other / not listed",
            "swahili_name": "Nyingine",
            "family": "",
            "wood_density": "",
        }
    )
    files["species_names.csv"] = (species_columns, species_rows)

    return files


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--out",
        type=pathlib.Path,
        default=pathlib.Path(__file__).resolve().parents[1]
        / "backend/tests/fixtures/xlsform/ucl-biomass-datasets",
        help="directory to write the five CSVs into",
    )
    parser.add_argument(
        "--villages",
        type=int,
        default=38_000,
        help="roughly how many village rows to generate (default: 38000, "
        "Tanzania's order of magnitude)",
    )
    parser.add_argument("--seed", type=int, default=20260903, help="PRNG seed")
    arguments = parser.parse_args()

    arguments.out.mkdir(parents=True, exist_ok=True)
    files = build(arguments.villages, arguments.seed)
    for file_name, (columns, rows) in files.items():
        path = arguments.out / file_name
        _write(path, columns, rows)
        print(f"  {path}  {len(rows):>7,} rows, {len(columns)} columns")
    print(f"\nWritten to {arguments.out}")
    print("Synthetic. Shaped like Tanzanian administrative data; not UCL's data.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
