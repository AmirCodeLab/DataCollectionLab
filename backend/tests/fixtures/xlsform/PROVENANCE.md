# Where these workbooks came from

**None of them was written by us, and that is the point.** A fixture authored
to suit the importer proves that the importer handles what its author already
knew about; these were written by other people for their own purposes, before
this importer existed, and they are what turned up the curly quotes, the
literal `default` values, the camelCase names, the nested repeats and the
blank-template-imports-to-nothing case.

| File | Source | Licence |
|---|---|---|
| `xl_date_ambiguous_v1.xlsx` | [XLSForm/pyxform](https://github.com/XLSForm/pyxform) `tests/fixtures/example_forms/` | BSD-2-Clause |
| `odk-widgets.xlsx` | pyxform `tests/fixtures/example_forms/widgets.xlsx` — the ODK "all widgets" sample | BSD-2-Clause |
| `ucl-biomass.xlsx` | pyxform `tests/fixtures/bug_example_forms/UCL_Biomass_Plot_Form.xlsx` — a University College London field survey | BSD-2-Clause |
| `choice_filter_test.xlsx` | pyxform `tests/fixtures/example_forms/` | BSD-2-Clause |

Unmodified, deliberately. Fixing a real form to make it import is how a corpus
stops being evidence.

The wider run that produced the roadmap — 27 workbooks — is not committed;
these four are the ones with distinct behaviour worth holding to. To re-run the
whole set, fetch pyxform and point `scripts/import_xlsform.py` at
`tests/fixtures/*/`.
