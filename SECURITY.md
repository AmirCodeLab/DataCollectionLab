# Security policy

## Status

**This project is pre-release and has not been audited.** Do not use it to
collect real respondent data yet. The sections below describe what the design
protects, what it does not, and what is known to be incomplete — read them
before deploying anywhere that matters.

## Reporting a vulnerability

Report privately through GitHub's **Security → Report a vulnerability** on this
repository, which opens a draft advisory only maintainers can see.

Please do **not** open a public issue for a security problem, and please do not
post one to a discussion or a pull request.

There is deliberately no email address here. A published address in a
`SECURITY.md` is a permanent personal detail in a public file; the advisory form
does the same job without one.

What helps, in rough order:

- what an attacker gains, concretely — not the class of bug but the outcome
- the smallest reproduction you have, and the commit you saw it on
- whether it needs a device on the project, a valid key, or neither

Expect an acknowledgement within a week. This is a small project; a fix may take
longer than an acknowledgement, and you will be told which is happening.

If you would like credit in the advisory, say so and how you want to be named.
If you would rather not be named, that is also fine.

## Supported versions

None yet, in the sense that word usually carries. There is no released version,
no backport branch and no security-update stream. `main` is the only supported
thing, and self-hosted installs are expected to track it.

That changes at the first tagged release, and this section changes with it.

## What the design actually protects

Worth stating plainly, because "encrypted" on its own means very little.

**Submission content, from the server operator.** A device generates a content
key per submission, wraps it to every active project key, and encrypts operation
values before they are pushed. The server stores ciphertext it cannot read.
Decryption happens where the private key is — in the browser, or in a terminal
holding the key file. The envelope is specified in
`specs/encryption-envelope-v0.1.md` and is normative; 8 conformance vectors hold
both implementations to the same bytes.

Three modes: nothing, sensitive fields only, or everything. Sensitivity
propagation is enforced at publish time in both engines, so a field derived from
a sensitive one cannot be published as readable.

**Data at rest on the device.** SQLCipher 4 with a raw 256-bit key on all three
clients. The key is generated on first run, never leaves the device, and is not
stored by the app: Android derives it inside the Keystore with nothing persisted
outside the TEE, iOS keeps it in the Keychain as `WhenUnlockedThisDeviceOnly`,
desktop in the OS credential store.

There is no fallback and no recovery. A build linked against plain SQLite would
write cleartext while looking perfectly healthy, so every driver checks the file
header after opening and refuses to start if it reads `SQLite format 3`.

**Media, from the moment of capture.** Camera buffer → compress in memory →
encrypt in memory → write chunks. The plaintext photograph never reaches the
filesystem. The staged chunks *are* the upload, so a resumed upload provably
sends the same bytes as the first attempt.

## What it does not protect

- **Metadata.** The server sees which device submitted what, when, against which
  form version, and how large it was. Encryption covers values, not the shape of
  the traffic.
- **A compromised device before sync.** Answers live in the device database
  until pushed. Full-disk encryption and the OS keystore are the boundary; an
  attacker with a live unlocked device has the data.
- **A lost project private key.** There is no escrow and no recovery. If the
  private half is lost, submissions encrypted to it are unreadable permanently.
  That is the intended property, and it is a real operational hazard.
- **Transport, on its own.** Run the server behind TLS. Nothing in the client
  pins a certificate, and the settings screen will happily accept a plain
  `http://` address because that is what a LAN test server is.

## Known security-relevant gaps

These are documented rather than quietly held. Full detail in
[`docs/known-defects.md`](docs/known-defects.md) and the "Plainly NOT done yet"
section of [`docs/project-conventions.md`](docs/project-conventions.md).

- **The app lock is off and cannot be switched on.** The keystore work exists —
  an auth-bound Android Keystore key, `kSecAccessControlUserPresence` on iOS —
  but the binding is fixed when the key is generated, so enabling it on a device
  that already holds data needs a database re-key that is not written. A toggle
  without it would silently destroy every answer on the device.
- **Key custody is half built.** Generation, registration and revocation work.
  Rotation is manual and unguided, there is no re-registration of a holder, and
  no import of a keypair generated elsewhere.
- **Every device in a project gets the production environment's forms** (defect
  3). A device's environment is derived rather than assigned, so a staging
  device cannot presently be kept off production forms.
- **A deployment cannot be retired** (defect 4), which is upstream of two
  measured dataset defects.
- **Nothing checks that a device's forms and its submissions agree** (defect 5).

## The test keypair in this repository is public on purpose

`scripts/dev_project_key.py` contains a **fixed private key, in version
control**. Anything encrypted to it is readable by anyone with a copy of this
repository. It exists so a developer can exercise the encrypted path end to end
without the console, which deliberately cannot be automated.

The guard rails are enforced, not documented: the script refuses to run outside
a development environment and refuses a project holding a key it did not
install, and the server refuses to register or hand out any of these published
public halves outside development
(`backend/app/modules/crypto/published_test_keys.py`). That server-side check is
what catches a development database later promoted to production.

If you find a way past either guard, that is a vulnerability worth reporting.

## Deployment notes that are security decisions

- `docker-compose.yml` ships development credentials (`dcp:dcp`,
  `minioadmin:minioadmin`) and `jwt_secret` defaults to
  `change-me-in-production`. They are defaults for a local stack, not a
  deployment baseline. Override all of them.
- Request logging records full request and response bodies, and submission
  bodies carry respondent data. It defaults on **only** when
  `ENVIRONMENT=development`. Setting `HTTP_LOG=true` in production is a decision
  about respondent privacy; `HTTP_LOG_BODIES=false` keeps the request lines
  without payloads.
