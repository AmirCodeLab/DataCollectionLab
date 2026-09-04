# Public-readiness audit

Run on 2026-09-04, against `phase2/server-url-settings` at the point the history
rewrite landed, plus the state of the GitHub repository itself.

**The findings are as found; the resolutions are dated and appended.** Each
section keeps its original text, and carries a **Resolution** block below it
saying what was done, what was accepted as-is, and what is still open. Nothing
above a resolution block is rewritten — that is the point of the format. An
audit showing what was found *and* what was done about it is worth more than a
clean one; a snapshot that has silently gone false is worth less than no audit
at all, which is what this one had become within the hour (finding 2 still read
BLOCKER after it was fixed).

Findings are ordered by what they cost if missed, not by effort. Status words in
the headings are current, not historical — each resolution names what the
finding was found as.

**Resolution passes:** 2026-09-04 (initial series), 2026-09-04 (going public).

## Method, and what it covers

Four passes, over both the tree and the rewritten history:

1. **Secrets** — key material, tokens, cloud credentials, high-entropy strings,
   across every blob in every commit (not just the tips).
2. **Personal and environment detail** — absolute paths, usernames, email
   addresses, private network addresses, device identifiers.
3. **Licensing** — the outbound licence, redistributed third-party material, and
   the licence of every runtime and development dependency against AGPL-3.0.
4. **Repository posture** — CI trigger safety, workflow permissions, ignore
   coverage, and the GitHub-side surface that a force-push does not reach.

## Clean — checked, nothing found

Recorded because an audit that lists only problems cannot tell you what was
actually looked at.

- **No secrets, in the tree or in any commit's blobs.** No private key material,
  no `AKIA…`, `ghp_…`, `xox…` or `sk-…` tokens, no cloud credentials. The one
  `BEGIN PRIVATE KEY` hit is a deliberately malformed 12-byte stub in
  `backend/tests/test_project_keys.py`, testing that a bad key is refused.
- **No absolute paths carrying the username in the tree.** Zero occurrences of
  a home directory named for the author. (See finding 1 — this is *not* true of the GitHub-side refs.)
  **Amended 2026-09-04:** this pass was text-only and therefore could not read
  the two tracked `.docx` files, one of which named a person in its metadata.
  See finding 11 — the result above was clean about text, not about the tree.
- **No real email addresses.** The single regex hit is a Kotlin `this@Class`
  qualifier, not an address.
- **No tracked junk.** No `.DS_Store`, IDE directories, `.env`, or build output
  under version control. `.gitignore` covers all of them plus the generated
  dataset CSVs and import reports.
- **CI is safe to expose to fork pull requests.** `ci.yml` triggers on
  `pull_request`, **not** `pull_request_target`, declares
  `permissions: contents: read`, and uses no repository secrets. This is the
  single most common way a repository is compromised on going public, and it is
  already right.
- **Every dependency is AGPL-compatible.** The runtime set is MIT/BSD/Apache-2.0
  throughout (FastAPI, SQLAlchemy, pandas, pyreadstat, boto3, cryptography;
  Ktor, Compose, SQLDelight, Koin, SQLCipher). The one copyleft dependency,
  `pglast` (GPLv3+), is development-only and compatible with AGPL-3.0 in any
  case.
- **Fixture provenance was already documented.** `PROVENANCE.md` correctly names
  all four workbooks, their upstream, and BSD-2-Clause.

## 1. CLOSED — the pre-rewrite history was still live on GitHub, in `refs/pull/*`

**This was the finding that mattered, and it is why this repository is not the
one the project started in.** Resolved on 2026-09-04 by publishing from a new
repository: the full rewritten history was pushed to a fresh remote, verified
commit-for-commit against the local copy, and the original was bundled and
deleted. This repository has never had a pull request, so `refs/pull/*` is
empty and there is nothing frozen behind the branches. Keep it that way —
merge branches locally rather than through a PR.

The original finding follows, because the reasoning is the reason for the move.

The force-push rewrote every branch. It did not — and cannot — touch the
snapshots GitHub keeps of merged pull requests. Right now, on the remote:

| Ref | Attribution trailer lines |
|---|---|
| `refs/pull/1/head` | 66 |
| `refs/pull/2/head` | 70 |
| `refs/pull/3/head` | 82 |
| `refs/pull/4/head` | 86 |

`refs/pull/5/*` updated to the rewritten commits, because PR #5 is open and
tracks the branch. The four merged ones are frozen at the old commits.

Reachable from all four, verified against the live remote: both
`local.properties` blobs, one of them carrying an `sdk.dir` under a home
directory named for the author. The value is deliberately not reproduced
here — quoting it in the file that asks for its removal is how it comes
back, which is the mistake finding 3 records one section down.

So both things the rewrite was for — the attribution and the username-bearing
SDK path — remain fetchable by anyone who can read the repository. Today that is
you alone. **The moment the repository becomes public, they are public**, by
`git clone --mirror`, by `git fetch origin 'refs/pull/*:refs/pull/*'`, and on
each PR's Commits tab.

Three ways out, and only one of them is free:

- **Publish from a new repository.** Push the rewritten history to a fresh repo,
  make that one public, and keep this one private as the archive. No PR refs
  exist there, so nothing to purge. Costs the issue/PR history and the stars and
  forks you do not yet have. This is the clean answer at your stage.
- **Ask GitHub Support to purge the unreachable objects and PR refs.** They will
  do it for a repository you own. It takes a few days and it does not need the
  PRs deleted.
- **Delete the four merged PRs.** You have already said no, and it is worth
  saying that this is the only self-service option that works — deleting a PR
  drops its refs.

Accepting it is also a position, but take it deliberately: the exposure is a
home-directory path and a machine-generated trailer, not a credential.

**Resolution — 2026-09-04 (going public).** The move to a fresh repository
holds: the history here is the rewritten one and the original is bundled and
gone. **But the advice in the paragraph above — "merge branches locally rather
than through a PR" — is superseded, deliberately.** As of 2026-09-04 `main`
carries a branch ruleset requiring a pull request and all five CI checks, with
no bypass list, because two merges had just landed on a red `main` and a bypass
for the only committer is a ruleset that applies to nobody.

That decision spends exactly what this finding bought. `refs/pull/1/head` now
exists, and every future change adds another. The reasoning above is unchanged
and still correct — those refs cannot be rewritten — so the protection moved
from *rewriting later* to *not committing it in the first place*, written up as
rule 11 in `docs/project-conventions.md`. The trade was made with this finding
in front of us, not in ignorance of it.

## 2. RESOLVED — `SECURITY.md` pointed at a button that did not exist yet

`SECURITY.md`, added in this series, directs reporters to GitHub's private
vulnerability reporting. That feature is **not enabled** on this repository —
`GET /repos/.../private-vulnerability-reporting` returns 404 — and it cannot be
enabled while the repository is private.

Enable it in **Settings → Advanced Security → Private vulnerability reporting**
at the same time you flip the repository public. If you publish without it, the
policy file names a channel that is not there, which is worse than naming none.

**Resolution — 2026-09-04 (going public). Resolved; found as BLOCKER
(procedural).** Private vulnerability reporting is **enabled**:
`GET /repos/AmirCodeLab/DataCollectionLab/private-vulnerability-reporting`
returns `{"enabled": true}`, and a logged-out visitor sees the **Report a
vulnerability** button on the Security tab beside the rendered `SECURITY.md`.
The channel the policy names now exists.

The second half of the finding — "it cannot be enabled while the repository is
private" — was overtaken: the repository went public at 09:14:09Z on
2026-09-04, about a minute before the first CI run on `main`. This section
asserted an open blocker for roughly an hour after it had stopped being true,
in a world-readable file, which is what prompted the resolution format.

## 3. CLOSED — your home network layout and a device id were in the docs

Seven occurrences, in prose recording the real hardware runs: six in
`docs/project-conventions.md` and one in break 35 of `docs/known-breaks.md`.
They named a specific private network, the two DHCP reassignments it handed out
mid-run, and a real device identifier.

RFC1918 addresses are not routable and exposed no service, so this was never
urgent — but they were load-bearing in neither document. The point of break 35
is that the app synced to the wrong address, which reads identically with a
placeholder.

Replaced with `192.168.1.20`, which is already the placeholder
`SettingsScreen` shows, so the docs and the UI now agree; the reassignments
became `.25` and `.31`, and the device id a generic one. The real values are
deliberately not restated here — an audit that quotes what it asked you to
remove republishes it.

**Resolution — 2026-09-04 (going public). Confirmed closed.** The placeholder
`192.168.1.20` is in place: three occurrences in `docs/project-conventions.md`
and one in break 35 of `docs/known-breaks.md`, with no occurrence of the real
network, the two reassignments, or the device id anywhere in the tree. Note the
scope: this is true of the tip. The original values are in earlier commits of
the rewritten history and, under rule 11, stay there.

## 4. SHOULD FIX — a self-hoster has no map of the configuration surface

There is no `.env.example` in the repository. The old README's first command was
`cp .env.example .env`, against a file that has never existed on this branch —
the README rewrite in this series removed that instruction, because the defaults
in `backend/app/core/config.py` genuinely do match `docker-compose.yml` and a
local run needs no `.env`.

What is still missing is the *discoverability*: the only way to learn that
`JWT_SECRET`, `S3_SECRET_KEY`, `HTTP_LOG` and `MEDIA_SESSION_TTL_SECONDS` exist
is to read the settings class. For a project inviting self-hosting, that is the
wrong place for it.

A recovered `.env.example` from an abandoned Aug-28 clone is saved at
`~/Backups/DataCollectionLab/env.example-from-dcp-repeats`. It is stale — it
predates the media and export settings — so it wants updating rather than
copying. Left as found.

**Resolution — 2026-09-04 (going public). Still open, accepted for now.** There
is still no `.env.example` at the repository root or under `backend/`. The
README's quick start is honest — the defaults do match `docker-compose.yml`, so
a local run needs no file — but the discoverability gap this finding names is
untouched: `JWT_SECRET`, `S3_SECRET_KEY`, `HTTP_LOG` and
`MEDIA_SESSION_TTL_SECONDS` are still only findable by reading
`backend/app/core/config.py`. Left as found, and it is the one *should fix* on
this list that is still outstanding.

## 5. CLOSED — `jwt_secret` defaulted to a known value with nothing to stop it

```python
jwt_secret: str = "change-me-in-production"
```

Nothing refused to start when `ENVIRONMENT != development` and the secret was
still the default. A self-hoster who missed one line signed tokens with a value
printed in this repository, with no symptom — everything works, because both
ends share the secret.

Closed the way the codebase already closes the equivalent for project keys:
`app/core/published_defaults.py` holds the constant and the refusal, `main.py`
refuses to start, and `Settings` imports the constant rather than repeating it,
so the value the guard recognises cannot drift from the value the application
falls back to. Break 71 records both halves watched to fail.

Related and still open: `docker-compose.yml` ships `dcp:dcp` and
`minioadmin:minioadmin`. Correct for a local stack, and now stated in
`SECURITY.md` as defaults rather than a deployment baseline. Left as found —
unlike the signing key, a database password that is wrong fails loudly.

**Resolution — 2026-09-04 (going public). Confirmed closed; second half
accepted.** `backend/app/core/published_defaults.py` holds the constant and the
refusal, `app/main.py` refuses to start before anything is wired up, and
`Settings.jwt_secret` imports the constant rather than repeating it. Break 71
records both halves watched to fail.

The related half is **accepted, not fixed**: `docker-compose.yml` still ships
`dcp:dcp` and `minioadmin:minioadmin` (three occurrences). That is deliberate —
correct for a local stack, named in `SECURITY.md` as defaults rather than a
deployment baseline, and unlike a signing key a wrong database password fails
loudly rather than silently.

## 6. CONSIDER — no per-file licence headers

Two files carry `SPDX-License-Identifier`. The AGPL is enforceable from
`LICENSE` alone, so this is hygiene rather than a defect, but per-file headers
are what survive a file being copied out of the repository — which is the case
the AGPL exists for. A one-line `SPDX-License-Identifier: AGPL-3.0-or-later` at
the top of each source file is the usual answer, and is mechanical.

**Resolution — 2026-09-04 (going public). Still open, accepted.** Unchanged.
The only files carrying `SPDX-License-Identifier` are `gradlew` and
`gradlew.bat`, which are Gradle's own and came with the wrapper — so in effect
no first-party file has a header. Still hygiene rather than a defect, and still
mechanical whenever it is wanted.

## 7. CONSIDER — the contributor surface is absent

No `CONTRIBUTING.md`, no code of conduct, no issue or PR templates. The
conventions a contributor needs are real and unusually well written, but they
are inside `docs/project-conventions.md` mixed with settled internal decisions,
and a first-time contributor will not find them.

Worth extracting the two rules the README now names — the spec is normative,
never edit a failing expectation — plus how to run the suites, into a
`CONTRIBUTING.md` that points back at the conventions document for the rest.

**Resolution — 2026-09-04 (going public). Still open, and now sharper.** No
`CONTRIBUTING.md`, no code of conduct, no issue or PR templates. This moved from
*consider* toward *should*: `main` now requires a pull request, so a
contributor's first interaction with the repository is a process nothing
documents. What they need is also more than it was — the five checks that must
pass, and rule 11, which is a constraint on what may enter a commit at all.

## 8. CONSIDER — actions pinned by tag, and no dependency updates

All seven third-party actions are pinned by moving tag (`actions/checkout@v4`)
rather than commit SHA. A compromised tag runs in CI. With `permissions:
contents: read` and no secrets the blast radius is small today, which is why
this is a *consider* and not a *should*.

There is also no Dependabot or equivalent configuration, so a public repository
gets no automated advisory for its dependencies.

**Resolution — 2026-09-04 (going public). Partly addressed; the rest still
open.** All seven actions are still pinned by moving tag
(`actions/checkout@v4`, `actions/setup-python@v5`, `actions/setup-node@v4`,
`actions/setup-java@v4`, `actions/upload-artifact@v4`,
`android-actions/setup-android@v3`, `gradle/actions/setup-gradle@v4`), and
there is still no `.github/dependabot.yml`.

What did change is the other half of the same question. The Python toolchain is
now pinned — `backend/requirements.lock` holds the resolved dependency set and
`.python-version` the interpreter — so a CI run no longer installs whatever PyPI
held that morning. That was fixed for a correctness reason rather than a supply
chain one (an unpinned toolchain made the byte-for-byte API contract check fail
at random), but it closes the same door. `web/` was already on
`package-lock.json` with `npm ci`. Gradle and the actions are what remain
unpinned.

## 9. NOTED — publishing `known-defects.md` and `known-breaks.md` is a strength

Worth stating explicitly because the instinct before going public is to remove
them. Both documents name real open defects, including security-relevant ones,
and `known-breaks.md` records guarantees watched to fail.

Publishing them is the honest position and an unusually strong signal about how
the project is run. `SECURITY.md` now references them by defect number rather
than hiding behind them. Recommendation: keep both, unchanged.

**Resolution — 2026-09-04 (going public). Confirmed, unchanged.**
Recommendation stands and both documents are published. `known-breaks.md` is
now at 72 rows; break 72 records the API contract differing by one line between
two Python versions, which is the kind of entry this document exists to make
publishable rather than embarrassing.

## 10. NOTED — closed by this series

- **BSD-2-Clause text was not travelling with the redistributed workbooks.**
  `PROVENANCE.md` named the licence; BSD-2-Clause requires the notice and
  disclaimer to accompany the copy. `NOTICE` now carries both, and states that
  the AGPL does not relicense those four files.
- **The README claimed Phase 0** while the tree is deep into Phase 2 part 1, and
  its first command referenced a file that does not exist.

**Resolution — 2026-09-04 (going public). Confirmed, unchanged.** Both remain
closed: `NOTICE` carries the BSD-2-Clause text and disclaimer, and the README
states Phase 2 part 1 in progress with a quick start whose commands exist.

## 11. RESOLVED — a personal name in two `.docx` files and their markdown twins

Found on 2026-09-04, after the passes above, by opening the binaries that none
of them opened.

Four tracked, publicly readable files named a person — a handle distinct from
the `AmirCodeLab` account the repository publishes under:

| File | Where |
|---|---|
| `docs/DCP-Product-Overview.docx` | `docProps/core.xml` `dc:creator`, **and the cover page** |
| `docs/DCP-Product-and-System-Architecture-v1.0.docx` | `docProps/core.xml` `dc:creator`, **and the cover page** |
| `docs/DCP-Product-Overview.md` | front-matter `author:` |
| `docs/DCP-Product-and-System-Architecture-v1.0.md` | `Owner:` on the subtitle line |

**How the earlier passes missed it, which is the more useful part.** Pass 2
searched the tree for absolute paths, usernames and email addresses. A `.docx`
is a zip of XML parts, so a grep over the working tree reads its compressed
bytes and matches nothing: the file was scanned and reported clean, which is
worse than not scanning it, because *"No absolute paths carrying the username in
the tree"* was recorded as a clean result while a name sat in `docProps`. The
two `.md` twins were plain text and greppable the whole time — they were missed
because the pass looked for path- and email-shaped strings, not for a name.
Every audit pass that greps a working tree has the first hole for every binary
format in it, and the second whenever the thing being looked for is not a
pattern.

**Resolution — 2026-09-04 (going public).** All four set to `AmirCodeLab` —
named rather than blank, because these documents go to clients and an empty
author reads worse than an attributed one. In the `.docx` files that is
`dc:creator` **and** the visible cover-page line, since fixing only the metadata
would have left the name on page one and made the change theatre. The rest of
`docProps` was checked in both: no `cp:lastModifiedBy` and no `cp:lastPrinted`
exist, `dc:title` is *"Data Collection Platform"*, `app.xml` has no `Company`
and no `Manager` (only `Template: Normal.dotm` and Word's own version strings),
and `custom.xml` holds a version date and a subtitle. Neither file contains an
email address, an absolute path, or embedded media. Both repack clean under
`unzip -t`; no occurrence of the old name remains anywhere in the tree.

**This changes only the tip, and that is accepted deliberately.** The blobs
carrying the old name are in earlier commits, and under rule 11 of
`docs/project-conventions.md` they stay there: `refs/pull/*` cannot be
rewritten and this repository now requires pull requests. The exposure is a
personal handle on a document, not a credential. The decision is to stop
republishing it going forward rather than to pretend it was never published —
which is the same decision, and the same reasoning, as finding 3.

## What this audit did not cover

Named so the gaps are not mistaken for clean results:

- **No dependency vulnerability scan.** No `pip-audit`, `npm audit` or Gradle
  equivalent was run. Licence compatibility was checked; known CVEs were not.
- **No code-level security review.** Nothing was read for injection, authz
  gaps, or crypto misuse. The envelope's *specification* and its conformance
  vectors were taken as given, not re-derived.
- **No review of the 27-workbook corpus** referenced in `PROVENANCE.md`, since
  it is not committed.
- **Nothing was verified about the iOS build**, which has not been re-run on a
  device since Phase 0.

- **Binary file metadata was not inspected** in the original passes, and no pass
  looked for a *name* as opposed to a path- or email-shaped string. That is how
  finding 11 was missed in four files, two of which were plain text. The two
  `.docx` files have since been opened and checked; no other binary format is
  tracked, but a pass that greps a working tree cannot see inside one and should
  not be recorded as having cleared it.
