# Gate 1 — provisioning

Analysis, before any code. The scope is the workflow agreed months ago and
never built: **create an organisation, create its first administrator, create a
project with its environments, and generate the project keypair in the browser
with the private key downloaded and never sent.**

Gate 1 exists because it is what makes every other gate possible on a server
that is not a laptop (`docs/what-rcons-does-not-have.md`).

Two of its deliverables are not code, and they are in §6 and §7: **key custody
written down as a procedure**, and **a restore actually performed**.

---

## 0. The decisions, and the answer to the question in front

**The question.** *What passes every test here?* Two things, and the second is
the one that would ship.

**The first is `POST /organizations`.** It is the obvious shape, every test
passes — a route that makes an organisation, guarded by a bootstrap token in an
environment variable. And it dissolves the rule every policy in this system
rests on. The application connects as `dcp_app`, never as the owner; the owner
engine exists for migrations and provisioning and its own docstring says
"nothing that serves a request may hold one". An organisation cannot be created
under row-level security, because there is no principal until it exists — so a
route that creates one either holds an owner connection or reaches through a
definer function wide enough to write `platform_organization`, `role` and
`role_permission`. Either way the boundary that item 1 built, item 2 narrowed
and item 5 defended stops being a boundary, and it stops being one on the path
that has no session by definition.

**The second is a keypair with no custodian.** The console already generates
the project keypair in the browser and downloads the private half — that part
works. What no screen and no document says is who keeps it. A product that
generates a key and hands it over without saying who holds it, where the backup
lives and what happens when that person leaves has shipped a trap, and the
trap springs months later when the data cannot be read. It is the only failure
in this system that no amount of later work recovers from.

**D1 — the line is the request path, not the API.** Provisioning splits in two,
and the split is not a preference:

- **Outside the request path, over the owner connection, run on the server:**
  the organisation, its four builtin roles and their permissions, and the first
  administrator. This is the same class of act as `alembic upgrade` — it
  happens once, an operator does it, and it needs a privilege no request may
  ever hold.
- **Inside the app, authenticated, as `dcp_app`, under the policies:** the
  project, its environments, and its keys. By then an administrator exists, so
  these are ordinary routes with an ordinary permission, and the console can
  offer them.

The seam is exactly where `session_for_organization` already puts it: before
the organisation is resolved there is no principal, and after it there is.

**D2 — the first administrator's password is never an argument, never printed,
never defaulted.** `scripts/seed_dev.py` publishes `dcp-dev` on purpose and
refuses to run outside development for that reason. The provisioning tool is
the opposite case: it prompts, so the password does not land in shell history
or a CI log, and it writes nothing to standard output that a screenshot would
leak.

**D3 — the tool refuses an organisation nobody could log into.** This
deployment resolves its organisation from the `dcp_org` cookie or, failing
that, from `ORGANIZATION_SLUG`, which defaults to `dev`. Provisioning a slug
that does not match the configured one produces an organisation that exists,
holds a working administrator, and cannot be reached by the login. The tool
compares them and refuses, naming both.

**D4 — the keypair step is not rebuilt.** It exists, it is correct, and the
envelope spec says exactly this: "Generated in the browser at project creation.
The private key is downloaded by the user and never transmitted to the server."
Gate 1 supplies the missing half — a project to generate it for — and adds
nothing to the key path except the custody wording around it.

**D5 — custody is stated where the key is generated, not only in a document.**
`project_key.role` has admitted `primary`, `backup` and `recovery` since 001
and nothing has ever used more than one of them. The procedure in §6 says what
must exist before a project collects real data; the keys screen should be able
to say whether it does. That is a small piece of product and §5 scopes it.

---

## 1. What exists today, plainly

**Works.**

- `POST /projects/{id}/keys` registers a public key with a role and a label;
  the console generates the pair in the browser, downloads the private half,
  and uploads only the public one. Revocation exists.
- `POST /people` creates a person; item 1's roles, teams and approval queue all
  work, and a supervisor can create their own enumerators.
- Migrations create the schema, and 008 seeds the four builtin roles **for the
  organisations that exist when it runs**.
- The `dcp_app` role's login is provisioned by `scripts/db_app_role.sql` on a
  fresh Postgres volume.

**Does not exist.**

- Any way to create an organisation outside `scripts/seed_dev.py`, which
  refuses to run outside development.
- Any way to create a project. There is no `POST /projects`; `project` rows
  come from the seed.
- Any way to create environments. The seed makes three, by fixed id.
- Any first-administrator path. The seed makes seven people with a published
  password.
- `deploy/` — one empty `.gitkeep` since the initial commit, while the README
  lists it as "Docker Compose and deployment tooling".
- Any statement, anywhere, about who holds a private key.

**The consequence, which is the reason this is gate 1:** every run this project
has ever done — all five end-to-end walks — has been against one seeded
organisation on a laptop. Nothing has ever been stood up.

---

## 2. What would pass every test

**1. The bootstrap route.** §0. Every test passes and the connection boundary
is gone, on the one path that has no session to check.

**2. The organisation nobody can reach.** Slug `rcons`, `ORGANIZATION_SLUG`
still `dev`. The rows are perfect. The login resolves nothing and the message
says the organisation is unknown, which is true and unhelpful.

**3. The password in the shell history.** `--admin-password` is the obvious
flag. It lands in `~/.zsh_history`, in the CI log, and in the screenshot of
the terminal that gets pasted into chat.

**4. The project with no environments.** Nothing refuses it. Deployments name
an environment, so a project without them accepts a form version and can
deploy it nowhere — and defect 3 means the device would want production
anyway.

**5. The keypair generated twice.** A second visit to the keys screen makes a
second primary key, both valid, and the one the operator kept is not
necessarily the one the first submission wrapped to. The envelope handles
multiple active keys by design; the *custody* does not, unless somebody wrote
down which file is which.

**6. The key with no custodian.** §0. The screen says "downloaded"; nothing
says by whom, or where the second copy is. Six months later the answer is a
person who has left.

**7. The backup that was never restored.** A `pg_dump` in a cron job is not a
backup until it has been read back. §7 is the only item on this list that
cannot be satisfied by writing code.

---

## 3. The model

### 3.1 The provisioning tool

`scripts/provision.py`, run on the server the way `alembic upgrade` is, over
the owner connection, and refusing to run against a database whose migrations
are not at head. It does four things and stops:

1. The organisation, by slug, compared against `ORGANIZATION_SLUG` (D3).
2. Its four builtin roles and their permissions — the same statements 008 and
   016 run, so a newly provisioned organisation is identical to a migrated one.
   This is the part that must not drift: §4 proposes it be one shared SQL file
   that both the migration and the tool execute.
3. The first administrator: username, display name, prompted password, an
   active organisation membership and the organisation-wide Admin grant.
4. Nothing else. No project, no environments, no keys — those are D1's other
   half and belong to a person with a session.

Idempotent by natural key, so running it twice is not a second organisation.

### 3.2 Projects, environments and keys, as routes

`POST /projects` under `project.manage`, which the Admin role holds. It creates
the project and its three environments in one transaction, because failure 4 is
a project that cannot deploy anything and there is no reason to allow it.

The keys screen then works exactly as it does now. The one addition is D5's:
the screen states what custody requires and whether this project has it.

### 3.3 What a project needs before it may collect

Named here because it is the difference between a project row and a project:

- an environment to deploy to (created with it, §3.2);
- a form version, published and deployed;
- in an encrypting security mode, a usable primary key — already enforced,
  `RecipientSetError` refuses a device whose project has no usable recipient;
- at least one person who can assign the sample.

Whether the console should say which of these are missing is a screen
decision, not a schema one.

---

## 4. Schema, in outline

**Probably none at all**, and that is worth stating as a target rather than
discovering halfway.

`platform_organization`, `role`, `role_permission`, `platform_user`,
`platform_org_membership`, `user_role`, `project` and `environment` all exist
and all carry policies. Provisioning writes rows into them; it does not need
new ones.

The one real change is a refactor with a rule behind it: **the builtin roles
and their permissions must have exactly one definition.** Today the statements
live in `008_identity.sql`, are amended by `010_people.sql` and `016_review.sql`,
and are *copied* into `scripts/seed_dev.py`. A fourth copy in the provisioning
tool is how a customer's Supervisor ends up without `submission.review` while
the dev one has it. One file, executed by the migration and by the tool, with a
test that the two produce the same grants.

If anything else wants a migration, that is the signal to re-read §3.1.

---

## 5. Routes and screens, in outline

- `POST /projects` — name, slug, security mode. Creates environments. Refuses a
  duplicate slug by name.
- Console: a "New project" action on the projects screen, and after it the
  existing keys screen, reached directly rather than by typing a URL.
- The keys screen gains the custody statement (D5): which roles exist, which
  are missing, and one sentence on what each is for.
- No screen for creating an organisation. That is deliberate and §0 says why.

---

## 6. Key custody — the procedure

This is a deliverable of gate 1, not a follow-up, and it is written in
`docs/key-custody.md`. Its content is a decision rather than a discovery, so
the analysis states the shape and the document states the rule:

- **Who holds the primary key**, by role rather than by name, and where the
  single copy lives.
- **A backup key**, generated at the same time, held by a different person, and
  never on the same machine.
- **A recovery key**, offline, held by whoever the customer names — and the
  fact that all three are equal to the envelope and different only in custody.
- **What happens when someone leaves**: which key is revoked, what stays
  readable (a wrap made before revocation still opens), and what must be
  re-wrapped.
- **What a lost key means**: for the submissions already wrapped to it, nothing
  can be done. Stated in those words, because a procedure that implies
  otherwise is worse than none.

## 7. The restore — performed, not documented

`deploy/` gets a compose file and a backup script, and then the script is used
for real: a database with data in it is dumped, destroyed, restored, and a
handset is made to sync against it afterwards. What is written down is what
actually happened, including anything that did not work the first time.

The handset half is not optional. A restored database with a device that
cannot sync into it is a restored database and a stopped survey, and defect 21
says exactly how that failure looks: the device sends a cursor the new
database has never issued, gets nothing, and reports **"All changes synced"**.

---

## 8. Assumptions this analysis was written under — say if any is wrong

**A1.** Organisation, builtin roles and the first administrator are an
**operator action over the owner connection**, run on the server like a
migration — never an HTTP route, because a route that creates an organisation
must hold a privilege no request may hold.

**A2.** Project, environments and keys are **ordinary authenticated routes**
under `project.manage`, because by then an administrator exists. The console
offers them.

**A3.** The first administrator's password is **prompted**, never an argument
and never printed.

**A4.** The tool **refuses a slug that does not match `ORGANIZATION_SLUG`**,
naming both. This deployment is single-tenant and provisioning must not create
an organisation the login cannot resolve.

**A5.** Creating a project creates its three environments in the same
transaction. A project that can deploy nowhere is not a project.

**A6.** The keypair path is **not rebuilt**. It works, and the envelope spec
already describes exactly what it does.

**A7.** The builtin roles and their permissions get **one definition**, shared
by the migration and the tool, with a test that they agree. Four copies is how
a customer's Supervisor loses a permission the dev one has.

**A8.** Key custody is a **document in this repository** (`docs/key-custody.md`),
and the keys screen states whether a project has what the document requires.
The document is a deliverable of this gate.

**A9.** The restore is **performed**, against a database holding real rows,
and a handset syncs against the restored database before it is called done.
What is written is what happened.

---

## 9. What this gate does not touch

- **Multi-tenancy.** One organisation per deployment, resolved by
  `ORGANIZATION_SLUG`. The schema carries `organization_id` everywhere and the
  policies are written for more; nothing here exercises that.
- **TLS, DNS, and where the server runs.** Named in `deploy/` and left to the
  operator; this gate produces a compose file and a backup script, not a hosting
  decision.
- **Defect 3** (every device gets production) and **defect 21** (a device with
  a stale cursor). Both are named in §7 because a restore meets them; fixing
  them is gate 3's, with the screens.
- **Password policy, rotation, lockout, SSO.** Item 1 chose a password and a
  session; none of that changes here.
