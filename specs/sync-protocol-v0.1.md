# Sync Protocol Specification v0.1

**Status:** Draft — Phase 0
**Spec dependencies:** Form IR v0.1

## 1. Model

A submission is not a document that gets uploaded. It is a **stream of operations**
that the server folds into a materialised state.

```
Client op log  ──push──►  Server op history  ──fold──►  Materialised state
                                    │
                                    └──► periodic snapshots
```

Reasons: resumable on bad networks, mergeable between devices, and the correction
audit trail comes for free.

## 2. Operation

```json
{
  "opId": "01J8Z...",
  "submissionId": "01J8Y...",
  "formId": "household_survey",
  "formVersion": 3,
  "kind": "set",
  "path": "members[2].age",
  "value": 34,
  "deviceId": "dev_a1b2",
  "actorId": "usr_9f3",
  "counter": 148,
  "wallClock": "2026-08-28T09:14:22Z"
}
```

| Field | Rule |
|---|---|
| `opId` | ULID, generated client-side. **The idempotency key** |
| `counter` | Monotonic logical counter per device. Never reset |
| `wallClock` | Diagnostic and audit only — **never** used for ordering |
| `kind` | `set`, `unset`, `repeat_add`, `repeat_delete`, `finalize`, `reopen` |

## 3. Ordering

Ordering is by `(counter, deviceId)`, never by wall clock. Device clocks are
wrong often enough in the field that clock-based ordering silently corrupts data.

> **Note:** `counter` is a per-device sequence number, not a Lamport clock — a
> device never advances its counter on ops it receives from elsewhere. Ordering
> by `(counter, deviceId)` is therefore deterministic — every replica converges
> on the same result — but it is **not causal**: a device that has made many
> edits will win against one that has made few, regardless of which edit
> actually happened later.

## 4. Push

```
POST /api/v1/sync/push
{ "deviceId": "dev_a1b2", "ops": [ ... ] }

200 { "accepted": ["opId", ...], "rejected": [ { "opId": ..., "reason": ... } ],
      "serverCursor": 90114 }
```

- Batches are bounded (default 500 ops or 1 MB).
- Replaying an already-accepted `opId` is a no-op that returns success. Retry is
  always safe.
- Rejection reasons: `unknown_form_version`, `not_authorized`, `submission_closed`,
  `malformed`. A rejected op never blocks the rest of the batch.

Client obligations — an HTTP 200 is not an acknowledgement, the response body is:

- An op is marked synced ONLY when its `opId` appears in `accepted`.
- A rejected op stays in the client outbox with its `reason` recorded, is
  surfaced to the user, and is retried on a later sync (rejections can be
  transient, e.g. a form version published after the fact). The server's
  idempotency makes a rejected-then-accepted op count exactly once.
- A non-2xx response acknowledges nothing: every op in the batch stays pending.

### Device registration

```
POST /api/v1/devices
{ "deviceId": "dev_a1b2", "platform": "android",
  "osVersion": "Android 14 (API 34)", "appVersion": "0.1.0" }

200 { "deviceId": "dev_a1b2", "projectId": "prj_...",
      "status": "registered" | "already_registered" }
```

The server rejects every op from a device it has never seen (`not_authorized`),
so a client registers before its first push. Registration is idempotent:
`already_registered` is success and clients may re-register freely. A revoked
device gets 403 and cannot register its way back in. Until enrollment tokens
exist (see §11), the device attaches to the deployment's single active project
— a deployment with several projects answers 409 `project_ambiguous`.

## 5. Pull

```
GET /api/v1/sync/pull?cursor=90114&scope=assignments,forms,datasets

200 { "ops": [...], "tombstones": [...], "nextCursor": 90350, "hasMore": true }
```

Cursor-based, resumable. The client persists `nextCursor` only after the batch is
durably written locally.

## 6. Conflicts

Field-level last-writer-wins by `(counter, deviceId)`, with `deviceId` as a
deterministic tiebreak so all replicas converge on the same result.

Exceptions requiring explicit merge:
- Both devices edited the same field on the same submission after it was finalised
- A repeat instance was deleted on one device and edited on another

Flagged conflicts surface in a supervisor merge UI. They are never silently resolved.

## 7. Tombstones

Deletion is an operation, not an absence. `repeat_delete` and submission deletion
emit tombstones carried in pull responses so every replica converges. Tombstones
are retained for the configured retention window, minimum 90 days.

## 8. Snapshots

Replaying an unbounded op log is a scaling failure waiting to happen. The server
snapshots materialised state every N ops (default 200) or on finalisation. A
fresh device pulls the latest snapshot plus subsequent ops.

## 9. Media

Media never travels inside the op stream.

```
POST /api/v1/media/upload-sessions   -> { uploadId, chunkSize }
PUT  /api/v1/media/upload-sessions/{uploadId}/chunks/{n}
POST /api/v1/media/upload-sessions/{uploadId}/complete  -> { mediaId, hash }
```

Chunked, resumable, content-hash addressed. The op stream references `mediaId`.
An op referencing media that has not yet arrived is accepted and marked pending.

## 10. Peer-to-peer

Device-to-device transfer exchanges signed op bundles. Because ops carry `opId`
and `counter`, merging a peer bundle uses the same idempotent path as a server
pull. No separate reconciliation logic.

## 11. Open questions for v0.2

- Lamport-style counter merge, especially for peer-to-peer where devices
  exchange ops directly
- Compaction policy for long-lived cases with thousands of ops
- Whether `finalize` should be a hard barrier or a soft state
- Conflict UI semantics for repeat reordering
- Signing and trust model for P2P bundles
- Backpressure when a device has been offline for months
