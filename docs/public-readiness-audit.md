# Public-readiness audit

Run on 2026-09-04, against `phase2/server-url-settings` at the point the history
rewrite landed, plus the state of the GitHub repository itself.

**Nothing in this document is fixed.** It is a report. Where a finding was
already closed by the licence/README/security commits in this same series, it
says so and why; everything else is left exactly as found so the decisions stay
yours. Findings are ordered by what they cost if missed, not by effort.

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
- **No absolute paths carrying the username in the tree.** Zero `/Users/amir`
  occurrences. (See finding 1 — this is *not* true of the GitHub-side refs.)
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

## 1. BLOCKER — the pre-rewrite history is still live on GitHub, in `refs/pull/*`

**This is the finding that matters. Everything else on this list is smaller.**

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

Reachable from all four, verified against the live remote:

```
551ec3a:local.properties          sdk.dir=/Users/amir/Library/Android/sdk
d2dd1eb:clients/local.properties  sdk.dir=
```

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

## 2. BLOCKER (procedural) — `SECURITY.md` points at a button that does not exist yet

`SECURITY.md`, added in this series, directs reporters to GitHub's private
vulnerability reporting. That feature is **not enabled** on this repository —
`GET /repos/.../private-vulnerability-reporting` returns 404 — and it cannot be
enabled while the repository is private.

Enable it in **Settings → Advanced Security → Private vulnerability reporting**
at the same time you flip the repository public. If you publish without it, the
policy file names a channel that is not there, which is worse than naming none.

## 3. SHOULD FIX — your home network layout and a device id are in the docs

Seven occurrences, all in prose recording the real hardware runs:

| Where | What |
|---|---|
| `docs/project-conventions.md` (6) | `192.168.2.44:8001`, the DHCP reassignments `192.168.2.49` → `.12`, and the device id `dev_aecfb103` |
| `docs/known-breaks.md` (1) | `192.168.2.44:8001` in break 35 |

These are RFC1918 addresses — not routable, and they expose no service. But they
do describe a specific private network and name a real device, and they are load
-bearing in neither document: the point of break 35 is that the app synced to
the wrong address, which reads identically with `192.168.x.y`.

Recommendation: replace with a documentation placeholder. Left as found.

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

## 5. SHOULD FIX — `jwt_secret` defaults to a known value with nothing to stop it

```python
jwt_secret: str = "change-me-in-production"
```

Nothing refuses to start when `ENVIRONMENT != development` and the secret is
still the default. A self-hoster who misses one line signs tokens with a value
printed in this repository, and there is no symptom — everything works.

This is the same failure shape the codebase already refuses elsewhere and has a
name for: `published_test_keys.py` makes the equivalent mistake unexpressible
for project keys by having the *server* refuse them outside development. The
same guard, applied at startup to `jwt_secret`, would close it. Left as found —
it is a behavioural change and belongs in its own commit.

Related, and lower: `docker-compose.yml` ships `dcp:dcp` and
`minioadmin:minioadmin`. Correct for a local stack, and now stated in
`SECURITY.md` as defaults rather than a deployment baseline.

## 6. CONSIDER — no per-file licence headers

Two files carry `SPDX-License-Identifier`. The AGPL is enforceable from
`LICENSE` alone, so this is hygiene rather than a defect, but per-file headers
are what survive a file being copied out of the repository — which is the case
the AGPL exists for. A one-line `SPDX-License-Identifier: AGPL-3.0-or-later` at
the top of each source file is the usual answer, and is mechanical.

## 7. CONSIDER — the contributor surface is absent

No `CONTRIBUTING.md`, no code of conduct, no issue or PR templates. The
conventions a contributor needs are real and unusually well written, but they
are inside `docs/project-conventions.md` mixed with settled internal decisions,
and a first-time contributor will not find them.

Worth extracting the two rules the README now names — the spec is normative,
never edit a failing expectation — plus how to run the suites, into a
`CONTRIBUTING.md` that points back at the conventions document for the rest.

## 8. CONSIDER — actions pinned by tag, and no dependency updates

All seven third-party actions are pinned by moving tag (`actions/checkout@v4`)
rather than commit SHA. A compromised tag runs in CI. With `permissions:
contents: read` and no secrets the blast radius is small today, which is why
this is a *consider* and not a *should*.

There is also no Dependabot or equivalent configuration, so a public repository
gets no automated advisory for its dependencies.

## 9. NOTED — publishing `known-defects.md` and `known-breaks.md` is a strength

Worth stating explicitly because the instinct before going public is to remove
them. Both documents name real open defects, including security-relevant ones,
and `known-breaks.md` records guarantees watched to fail.

Publishing them is the honest position and an unusually strong signal about how
the project is run. `SECURITY.md` now references them by defect number rather
than hiding behind them. Recommendation: keep both, unchanged.

## 10. NOTED — closed by this series

- **BSD-2-Clause text was not travelling with the redistributed workbooks.**
  `PROVENANCE.md` named the licence; BSD-2-Clause requires the notice and
  disclaimer to accompany the copy. `NOTICE` now carries both, and states that
  the AGPL does not relicense those four files.
- **The README claimed Phase 0** while the tree is deep into Phase 2 part 1, and
  its first command referenced a file that does not exist.

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
