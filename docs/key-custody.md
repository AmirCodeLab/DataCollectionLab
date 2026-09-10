# Key custody

**This is a procedure, not a feature.** The platform generates a project's
keypair in a browser and downloads the private half; it never receives it and
cannot help you if it is lost. Everything below is about people and where they
keep a file.

It exists because the absence of it is the one failure in this system that no
later work recovers from. A submission encrypted to a key nobody holds is
gone — not slow to read, not awkward to read. Gone.

Read this before creating a project in `field_level` or `project_e2e` mode.
A `standard` project stores answers in plaintext and none of this applies to
it; that is the trade `standard` is.

---

## 1. What exists, technically

Per project, `project_key` holds one row per key: a 32-byte X25519 public key,
a role of `primary`, `backup` or `recovery`, a human label, and a revocation
timestamp. Every content key is wrapped to **every active project key**, so all
three roles can open everything wrapped while they were active.

The roles are **identical to the cryptography and different only in custody**.
Nothing in the code treats `backup` differently from `primary`. The distinction
is entirely about who holds the file and where — which is exactly why it needs
writing down rather than implementing.

The private half exists only as the file the browser downloaded. It is not on
the server, not in a backup of the server, and not recoverable from one.

---

## 2. The rule

**Before a project collects real data it has three keys, held by three
different people, in three different places.**

| Role | Who holds it | Where it lives | Used for |
|---|---|---|---|
| `primary` | The person who reviews data day to day — in the pilot, the programme manager | Their working machine, in the password manager the organisation already uses | Opening submissions in the console, daily |
| `backup` | A second named person, not on the same team and not on the same machine | Their own password manager | Opening submissions when the first person is unavailable |
| `recovery` | The organisation, not a person — the finance or operations lead who holds other irreplaceable things | Offline. Printed or on removable media, in whatever the organisation already uses for irreplaceable documents | Never, until it is the only one left |

**Generate all three at project creation, in one sitting.** A backup key added
later cannot open anything wrapped before it existed, because wraps are made at
push time to the keys that were active then. A project that runs for a month on
one key has a month of data with one custodian, whatever is added afterwards.

**The recovery key is never used routinely.** Every use is a copy in one more
place. If it is opening submissions on a Tuesday it has stopped being a
recovery key.

---

## 3. The labels are the record

`project_key.label` is free text and it is the only place the custodian is
written down. Use a form that survives someone reading it in two years:

```
Programme lead — Fatima Iqbal — primary — 2026-09
Field ops — Ahsan Malik — backup — 2026-09
RCons operations — recovery — offline — 2026-09
```

A label of "key 1" is a key with no custodian, which is the thing this document
exists to prevent. The keys screen shows the label, the role, the fingerprint
and the creation date; that is the register.

---

## 4. When someone leaves

1. **Revoke their key** on the project keys screen. Revocation stops new wraps
   being made to it and changes nothing about old ones — **a wrap made before
   revocation still opens**, and it has to, or every submission collected
   during that person's tenure would become unreadable the day they left.
2. **Generate a replacement** in the same role, labelled with the new
   custodian.
3. **Understand what the replacement can and cannot read.** It opens everything
   pushed after it was registered. It cannot open what was collected before,
   because those wraps were made to the keys that were then active. The
   surviving `backup` and `recovery` keys are what read that history — which is
   the whole reason they exist.
4. **Ask for the old file back, and assume you did not get it.** The
   cryptography cannot make a downloaded file disappear. Revocation is a
   statement about the future.

If the leaver held the **only** key, see §6.

---

## 5. When a handset is lost

Different problem, and a smaller one. A device holds its own content keys and
whatever it collected; it does not hold a project private key and never has.

- Revoke the device (`device.revoke`). Its ops are refused `not_authorized`
  from the next push.
- Its local database is encrypted at rest, with the key held in the platform
  keystore and, on Android, derived inside the hardware Keystore.
- What is lost is the work on it that had not synced. That is a data-loss
  question, not a key-custody one, and the answer is how often the team syncs.

---

## 6. When a key is lost

Say it plainly, because a procedure that implies otherwise is worse than none:

**If every key active when a submission was pushed is lost, that submission
cannot be read. By anyone. Ever.** There is no reset, no support path and no
escrow. The server holds ciphertext and never held anything else.

What can still be done:

- Submissions pushed **after** a surviving key was registered are readable with
  that key.
- The metadata is readable regardless: who collected, when, which case, which
  form version, which rules flagged it. Only the answers are ciphertext.
- Collection continues. Register a new key and everything from that moment is
  readable.

The recovery key exists so that this section never applies. It is worth the
inconvenience precisely once.

---

## 7. What to check before fieldwork starts

A short list, and all of it is visible on the project keys screen:

- [ ] Three keys, roles `primary`, `backup`, `recovery`, all active.
- [ ] Three different custodians, named in the labels.
- [ ] The recovery key is somewhere the other two people cannot reach.
- [ ] Somebody other than the person who generated them has **opened a
      submission** with the backup key. An untested key is a file, not a
      backup — the same rule as the database restore
      (`docs/restore-drill-2026-09-10.md`), for the same reason.
- [ ] The fingerprints of all three are recorded outside this system, so a key
      file can be matched to its row later.

---

## 8. What this does not cover

- **`standard` mode.** No project key, no custody, answers in plaintext in the
  database, protected by database access and nothing else.
- **The object store.** Media is encrypted with the same envelope; the custody
  of the project key covers it. Where the bucket's own credentials live is a
  hosting question.
- **Key rotation on a schedule.** Not built and not needed at pilot scale.
  Revoke-and-replace in §4 is the whole mechanism.
- **Multiple projects.** Each has its own keys. Three custodians per project,
  not three for the organisation.
