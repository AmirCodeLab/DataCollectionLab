# Data Collection Platform — Product & System Architecture

**Final baseline for product and engineering planning**
**Version 1.0 · 28 August 2026 · Owner: AmirCodeLab**

This document merges the v0.1 product plan with the v1.0 system architecture draft. It is the single baseline from which the Phase 0 specifications are written. Everything marked **LOCKED** is settled. Everything marked **CONDITIONAL** is settled subject to a Phase 0 spike. Everything marked **OPEN** must be answered before Phase 1 begins.

---

## 1. Product definition

DCP is an **offline-first field data and operations platform**. It covers the full operational cycle:

> assignment → collection → validation → supervision → review → approval → analytics

It is not a survey app. The field application is a *client* of the platform, not the platform itself. A customer who only wants forms can use it as a survey tool; a customer running inspections, longitudinal health studies, asset audits, or a 400-enumerator census operation uses the same primitives.

### 1.1 The five foundational systems

Everything else is built on these. If any one of them is weak, the product fails regardless of feature count.

| # | System | Responsibility |
|---|---|---|
| 1 | **Form Compiler + IR + Runtime** | One versioned internal representation, deterministic semantics on every target |
| 2 | **Entity, Dataset & Case model** | Model the real world, not flat surveys |
| 3 | **Offline + Sync engine** | Operation log, resumable, idempotent, conflict-aware |
| 4 | **Workflow + Quality engine** | States, transitions, SLAs, automated and human QC |
| 5 | **Web, Analytics & Integration platform** | Supervision, monitoring, reporting, external systems |

### 1.2 Product principles

| Principle | Requirement |
|---|---|
| Offline-first | Forms, logic, validation, cases, datasets, media and queued sync all work with no connectivity. Offline is a constraint on every feature, not a feature |
| Deterministic | Identical form semantics on Android, iOS, Desktop, Web and server. Enforced by conformance suite, not by convention |
| Migration-friendly | XLSForm/ODK concepts import into our IR. Compatibility lowers switching cost; it is not our runtime |
| Enterprise-ready | Tenant isolation, RBAC, audit, MFA/SSO, encryption, device management, self-hosting |
| Quality-first | Automated validation, operational checks, anomaly detection and human review |
| Extensible | Versioned REST API, webhooks, integrations, constrained custom widgets |
| Observable | Sync state, quality state and workflow state are visible to field users and supervisors, not hidden |

---

## 2. Positioning

### 2.1 Competitive reference

| Reference | What to learn | Our differentiation |
|---|---|---|
| **SurveyCTO** (primary) | Mature offline collection, cases, QC audits, security, integrations | Migration centre, transparent sync, workforce operations, analytics UX, self-hosting, price |
| **ODK ecosystem** (secondary) | Standards, XLSForm/XForms concepts, field workflows | Compatibility without making XLSForm the internal runtime |
| **KoboToolbox** (secondary) | Accessible humanitarian/research collection | Stronger enterprise workflow, QC, operations, device and analytics capability |

The goal is not a UI clone. Compatibility lowers switching cost; the moat is the runtime, the sync engine, the entity/workflow model, and operations.

### 2.2 Our differentiators

1. **One form engine, everywhere.** SurveyCTO maintains JavaRosa for mobile and a separate JavaScript engine for web forms; they drift. We write the engine once in KMP and run identical logic on Android, iOS, desktop, web and server validation.
2. **Self-hosting as a first-class product.** Docker Compose for small deployments, documented backup/restore/upgrade. SurveyCTO offers nothing here. This is the only route into government, defence and regulated-health buyers.
3. **Operations, not just collection.** A real workflow engine with assignment, SLA, escalation and correction loops. Competitors bolt approval onto a submission list.
4. **Transparent, resumable sync.** Field-level operation log, not finalise-and-upload-whole-submission. Resumable on bad networks, mergeable across devices, full history for free.
5. **Analytics that replace the export.** Saved views, cross-tabs, charts, maps, scheduled reports — so users stop exporting to Stata and Power BI for basic monitoring.
6. **Workforce layer.** Assignment routing, geofenced attendance, supervision, messaging, incentive tracking. Survey firms run this on spreadsheets today.

### 2.3 First market — **DECIDED: survey and research agencies**

Decided 4 September 2026, on the rule this section always carried: by which existing relationship signs first, not by market size. **RCons is the pilot customer** — a survey firm running household listings in Sindh. The analysis of their existing system is `docs/rcons-current-system.md`; the phase that follows from it is `docs/phase3-pilot-scope.md`.

The two candidates pulled the roadmap in opposite directions:

| Choice | What moves up | What can slip |
|---|---|---|
| **Survey & research agencies** — chosen | Workforce ops, per-seat pricing, Stata/SPSS export, QC audits, migration centre | Self-hosting, E2EE, data residency |
| Government / health ministries | Self-hosting, data residency, E2EE, audit, compliance | Workforce ops, advanced analytics |

**What the decision changes.** Self-hosting, data residency and SSO move back — they are what a ministry buys and not what a survey firm does; none of them blocks a pilot. Assignment, supervision and review move forward, out of the workforce module and into the next phase, because they are the daily work of a survey firm and the platform cannot run fieldwork without them: it knows a device but not a person.

E2EE is the one row of this table that did not slip. It was built ahead of the decision — client-side encryption, the envelope spec, per-project key custody — so the table's "what can slip" column is a record of what was weighed, not of what happened.

Phase 1 scope is no longer provisional.

---

## 3. Core product modules

| Module | Scope |
|---|---|
| Identity & Organization | Tenants, organizations, projects, users, teams, invitations, roles, permissions, MFA/SSO, service accounts |
| Project & Environment | Development / Staging / Production environments, configuration, templates, deployment policy |
| Form Builder | Visual builder, question palette, properties, logic, calculations, validation, translations, preview, testing |
| Form Compiler / IR | Visual builder, XLSForm/ODK and AI inputs compiled into a versioned internal IR/AST |
| Form Runtime | Navigation, expressions, relevance, validation, calculations, repeats, dynamic choices, metadata |
| Entity & Dataset Engine | Entity types, relationships, datasets, preload data, versions, lookups |
| Case Management | Cases, visits, history, status, assignment, reassignment, geographic targeting |
| Workflow Engine | States, transitions, triggers, actions, approvals, correction loops, SLAs, escalation |
| Offline Field Client | Forms, cases, datasets, media, GPS, local validation, drafts, outbox |
| Sync Engine | Push/pull, checkpoints, retries, resumable transfer, idempotency, conflicts, snapshots, tombstones |
| Submission & Review | Submission lifecycle, immutable payload, review queues, correction, approve/reject |
| Data Quality | Rules, duplicates, GPS/duration checks, text and audio audits, anomaly detection, quality scores |
| GIS | Points, lines, polygons, geofences, spatial assignment, map visualisation, offline basemaps |
| Media | Images, audio, video, signatures, files; compression, checksums, resumable upload |
| Workforce Operations | Assignments, attendance, supervision, training, messaging, optional incentive workflows |
| Monitoring | KPIs, enumerator activity, completion, backlog, sync health, errors, maps |
| Analytics & Reporting | Tables, charts, maps, saved reports, schedules, exports |
| Integrations | REST API, webhooks, API keys, service accounts, connectors |
| Notifications | Push, email, in-app workflow/assignment/review notifications |
| AI | Form generation and review, translation, anomaly assistance, transcription, report assistance |
| Device Management | Registration, health, app version, revocation, remote logout, controlled data reset |
| Audit & Compliance | Immutable administrative/security/data events, retention and export policy |
| Migration Center | Import, compatibility analysis, conversion, warnings, preview, testing, deployment |

---

## 4. Form Compiler, IR & Runtime

The form system is the technical heart. The internal representation is independent of XLSForm, XForms and any single UI.

```
Visual Builder  ┐
XLSForm         ├──► Form Compiler ──► Versioned Form IR / AST ──► Runtime + Expression Engine
ODK/XForms      │                                                   │
AI specification┘                                                   ├─► Android
                                                                    ├─► iOS
                                                                    ├─► Desktop
                                                                    ├─► Web (Wasm)
                                                                    └─► Server validation
```

| Input | Result |
|---|---|
| Visual builder | Validated Form IR |
| XLSForm | Form IR + compatibility warnings |
| ODK/XForms-compatible source | Form IR + compatibility report |
| AI specification | Draft Form IR requiring human validation and approval |

**Do not use XPath strings as the internal representation.** Parse to a typed AST at authoring time. This gives static error checking in the builder, a visual condition editor, safe evaluation, and no XPath dependency across five targets.

Published versions are **immutable**. Every production submission records the exact form version used.

### 4.1 Runtime requirements

- Relevance / skip logic
- Conditional required fields
- Constraint expressions, with soft constraints (warn + override with reason)
- Calculated fields
- Repeat and nested repeat groups
- Dynamic and cascading choices
- Entity / dataset lookup
- Date, time and numeric functions (including Hijri calendar)
- Randomisation of choices and question blocks
- Form metadata capture
- Pre-publication linting
- **Explainable logic path in test mode** — show why a question was shown, skipped or calculated
- Cross-target conformance tests

**Architecture gate:** the same conformance suite must pass on Android, iOS, Desktop, Web and server before the engine is considered production-ready. No large builder UI is built until it does.

### 4.2 Server-side evaluation — **OPEN**

The server must evaluate the same expressions for submission validation and server-side calculations. Two options:

- **(a) JVM engine sidecar** — run the Kotlin engine as a service FastAPI calls. Guarantees identical behaviour. Adds a JVM to every deployment including self-hosted.
- **(b) Python port** — simpler to operate; both implementations tested against the shared conformance suite in CI.

**Recommendation: (a).** Client/server semantic divergence is the bug class that destroys trust in a data platform, and a conformance suite catches divergence only for cases someone thought to write. Resolve in Phase 0.

---

## 5. Entity, Dataset & Case architecture

Model real-world entities rather than forcing every workflow into a flat survey. Example: Household → Members → Plots → Crops.

| Concept | Purpose |
|---|---|
| Entity Type | Definition — Household, Patient, Farm, School, Asset |
| Entity | Concrete record of an entity type |
| Relationship | Typed link between entities |
| Dataset | Reference / preload data |
| Dataset Version | Immutable published dataset version |
| Case | Operational wrapper: entity + workflow + field task |
| Visit | A collection event against a case |

Separating **Case** from **Visit** is what makes longitudinal studies, repeat inspections and multi-round fieldwork clean rather than hacked. Datasets sync incrementally to devices — never full re-download.

---

## 6. Workflow engine

Workflow is a first-class service, not a status column.

```
Assigned → In Progress → Submitted → Automated QC → Supervisor Review
                                                      ├─► Approved → Closed
                                                      └─► Correction Required → Resubmitted → (QC)
```

| Object | Responsibility |
|---|---|
| Definition | States, transitions, conditions, actions |
| Instance | Runtime state for a case or submission |
| Trigger | Submission, schedule, quality event, assignment, external event |
| Action | Notify, assign, approve, reject, create task, call webhook, update status |
| SLA | Deadline and escalation policy |

Offline-safe field transitions are permitted where possible; server authority is final for security-sensitive and cross-user actions.

---

## 7. Offline-first and synchronisation

### 7.1 Client model

- Local SQLDelight database for forms, assigned data, cases, drafts and sync state
- Offline form logic, validation and calculation
- Local media staging with asynchronous upload
- Outbox for operations
- Exponential-backoff retries
- Idempotency keys on every mutation
- Per-record and per-operation sync state
- Safe behaviour across app restart, OS suspension and intermittent connectivity
- Explicit sync diagnostics visible to field users and supervisors

### 7.2 Sync protocol

**Model: local operation log + materialised state + server operation history + periodic snapshots.**

Every submission is a stream of operations: `{submission_id, field_path, value, device_id, logical_counter, wall_clock, actor}`. The client appends locally and uploads in batches; the server acknowledges by operation id and folds the log to reconstruct current state.

| Requirement | Decision |
|---|---|
| Idempotency | Mandatory operation and request IDs |
| Ordering | Per-record logical ordering; never wall-clock alone |
| Retry | Every operation safely retryable |
| Resume | Cursor/checkpoint pull; resumable chunked media by content hash |
| Conflict | Field-level last-writer-wins by (logical counter, device id); explicit merge UI for flagged fields |
| Snapshots | Periodic snapshots prevent unbounded replay |
| Tombstones | Required for safe deletion propagation |
| Audit | Operation history retained per policy — gives the correction audit trail for free |

**No single "sync everything" call.** Synchronisation is incremental, resumable and observable.

### 7.3 Peer-to-peer transfer

Device-to-device transfer of submissions, cases and assignments with no internet, using Nearby Connections on Android and MultipeerConnectivity on iOS. Already prototyped in existing work — carry it forward, do not drop it.

---

## 8. Data quality and review

| Layer | Capability |
|---|---|
| Client validation | Required, range, format, constraints, cross-field checks |
| Server validation | Schema, version, authorization, integrity |
| Operational QC | Duration, GPS, device and sync metadata |
| **Text audits** | Time per question, navigation order, edit count |
| **Audio audits** | Random or triggered background recording during administration |
| **Speed limits** | Flag or block completion that is implausibly fast |
| Geofence validation | Was the submission taken inside the assigned area |
| Statistical QC | Duplicates, near-duplicates, outliers, plausible-range checks, suspicious patterns |
| Human review | Queue, comments, correction, approve/reject, push-back to device for re-visit |
| Enumerator scorecards | Completion rate, flag rate, average duration, rejection rate |
| Fraud heuristics | Identical answer patterns, impossible travel speed, off-hours work |
| AI assistance | Explainable anomaly suggestions requiring human confirmation |

Text audits, audio audits and speed limits appear by name on competitor RFP checklists. They are not optional.

---

## 9. Media pipeline

```
Capture → local staging → compression/normalisation → checksum → resumable upload
        → object storage → metadata record → short-lived signed access URL
```

Media capture must never require connectivity. Compression settings are configurable per project.

---

## 10. Workforce operations

A modular extension in code, a headline capability in positioning.

- Assignments, workload and territory allocation
- Attendance and time capture, geofence-based where appropriate
- Supervisor field visits
- Training and certification tracking
- Field messaging and broadcast
- Optional incentive / piece-rate workflows

---

## 11. Analytics and reporting

| Stage | Architecture |
|---|---|
| MVP | PostgreSQL with indexed reporting queries |
| V1 | Parquet + DuckDB analytical jobs |
| Scale | Optional ClickHouse or warehouse, after measured need |

Reports expose project, form version, filters, generation time and data freshness. Export formats: CSV, XLSX, **Stata (.dta), SPSS (.sav)**, GeoJSON/KML, media bundles. Wide and long formats for repeats.

Stata and SPSS export is a procurement blocker in the research market. `pyreadstat` makes it cheap; there is no reason to defer it.

---

## 12. Migration Center

Migration is a customer-facing product feature, not an import script.

```
Upload → Compatibility Analysis → warnings / unsupported features
       → Convert → Preview → Test → Approve → Deploy
```

| Source | Priority |
|---|---|
| XLSForm | P0 |
| ODK-compatible forms | P0 |
| CSV / reference datasets | P0 |
| SurveyCTO migration assistance | P1 |
| Kobo-compatible workflows | P1 |

**Never promise universal automatic migration.** Always produce an explicit compatibility report and an editable converted form. This ships in Phase 1, not Phase 2 — switching cost is the single largest obstacle to every deal.

---

## 13. API and event architecture

| Group | Examples |
|---|---|
| Auth | `/auth/login`, `/refresh`, `/logout`, `/sessions` |
| Projects | `/projects` |
| Forms | `/forms`, `/forms/{id}/versions` |
| Entities | `/entity-types`, `/entities`, `/relationships` |
| Cases | `/cases`, `/cases/{id}/visits` |
| Submissions | `/submissions` |
| Sync | `/sync/pull`, `/sync/push` |
| Media | `/media/upload-sessions` |
| Review | `/submissions/{id}/review` |
| Workflow | `/workflows`, `/workflow-instances` |
| Exports | `/exports` |
| Integrations | `/api-keys`, `/webhooks` |
| Devices | `/devices` |

Events use the **transactional outbox** pattern: database transaction → outbox event → worker → notification / analytics / webhook. Kafka or NATS only if volume or organisational boundaries later justify it.

Additionally: an **OpenRosa-compatible ingest endpoint** so existing ODK Collect installations can point at us during migration.

The web console consumes the same public API customers get. No private endpoints.

---

## 14. Security and privacy

- TLS everywhere; secure session and browser configuration
- Short-lived access tokens with rotating refresh tokens
- Device and session revocation
- Least-privilege RBAC plus policy checks
- Tenant isolation enforced on every authorization path
- Immutable audit events
- Encrypted local storage using platform cryptographic facilities (Keystore / Keychain, SQLCipher)
- Server-side object-storage encryption; short-lived signed media URLs
- Rate limiting and brute-force protection
- Managed secrets; no production secrets in source control
- Dependency, container and secret scanning in CI
- Threat modelling and independent security review before enterprise rollout

### 14.1 Three security modes

| Mode | Description |
|---|---|
| Standard | Queryable data, encrypted at rest and in transit |
| Field-level encryption | Named sensitive fields encrypted; the rest stays queryable so dashboards and QC still work |
| Project-level end-to-end | Envelope encryption, private key never on the server; decryption client-side only |

**Phase 0 requirement.** The envelope format, key custody and the field-level encryption boundary are specified in Phase 0 even though the E2EE feature ships later. Building the ingest, review and analytics pipeline on an assumption of plaintext makes E2EE a rewrite rather than a feature.

The reference scheme: per-submission AES-256-GCM key; instance data and each media file encrypted with distinct IVs; the symmetric key wrapped with the project/form public key; private key downloaded at creation and never stored server-side.

---

## 15. Multi-tenancy and environments

| Model | Approach |
|---|---|
| SaaS | Schema-per-tenant in shared PostgreSQL, with application authorization and database controls |
| Enterprise / private cloud | Dedicated database or infrastructure |
| Self-hosted | Dedicated installation |

Every project supports **Development, Staging and Production** environments. Production form versions are immutable. Project templates may clone forms, datasets, workflows, roles, dashboards and quality rules without copying production records.

A **Data Dictionary** is generated per project: variable name, label, type, choices, description, unit, validation, sensitivity classification, source form/question, version.

---

## 16. Device management

| Capability | Requirement |
|---|---|
| Registration | Device ID, user, project, OS, app version |
| Health | Last sync, storage, battery, operational state where available |
| Security | Revoke device or session, remote logout |
| Operations | Force or recommend sync, require app update |
| Data | Controlled project-data reset with authorization |

---

## 17. AI

AI is **table stakes, not a differentiator** — competitors already ship form assistants. Build it because its absence is noticed, not because its presence sells.

| Capability | Target |
|---|---|
| Form logic / validation reviewer | V1.5 |
| Translation assistant | V1.5 |
| Natural-language form generator | V1.5 / V2 |
| Data anomaly assistant | V2 |
| Speech transcription | V2 |
| Narrative / report generation | V2 |

AI never silently changes production forms or data. Every AI-generated artifact requires validation, explicit approval and audit.

---

## 18. Technology stack

### 18.1 Backend and data — LOCKED

| Layer | Choice | Why |
|---|---|---|
| Language | Python 3.12+ | Unmatched export/stats ecosystem (pandas, pyreadstat) |
| Framework | FastAPI | Async, OpenAPI generation, Pydantic validation |
| Architecture | Modular monolith | Lower operational complexity; extract services only on measured need |
| ORM / migrations | SQLAlchemy 2.0 async + Alembic | Migration maturity matters for self-hosted upgrades |
| Database | PostgreSQL 16 + JSONB | Transactions, flexible payloads, mature ecosystem |
| GIS | PostGIS | Spatial queries, geofencing |
| Cache / queue | Redis + Celery (or Arq) workers | QC checks, exports, publishing, schedules |
| Object storage | S3-compatible; MinIO bundled for self-host | Media, attachments, exports |
| Analytics | Parquet + DuckDB initially | No premature warehouse; no extra infra for self-hosters |
| Observability | OpenTelemetry, metrics, centralised logs; Sentry on clients | — |
| Packaging | Docker | Consistent cloud and self-hosted deployment |
| Orchestration | Kubernetes deferred | Only when justified by scale |

### 18.2 Field clients — LOCKED except UI

| Layer | Choice |
|---|---|
| Shared code | Kotlin Multiplatform — **LOCKED** |
| UI | Compose Multiplatform — **CONDITIONAL** on Phase 0 iOS spike; SwiftUI over the shared core is the escape hatch, so the UI/core boundary stays strict |
| Local DB | SQLDelight — LOCKED |
| Networking | Ktor Client — LOCKED |
| DI | Koin — LOCKED |
| Serialisation | kotlinx.serialization — LOCKED |
| Local encryption | SQLCipher; Android Keystore / iOS Keychain | 
| Maps | MapLibre Native, offline basemaps |
| Camera / media | CameraX (Android), AVFoundation (iOS) via expect/actual |
| Background sync | WorkManager (Android), BGTaskScheduler (iOS) |
| Desktop packaging | Compose Desktop → MSI / DMG / DEB |
| P2P | Nearby Connections (Android), MultipeerConnectivity (iOS) |

### 18.3 Web console — LOCKED

| Layer | Choice | Why |
|---|---|---|
| Framework | React 19 + TypeScript | Largest hiring pool, best grid/chart ecosystem |
| Build | **Vite SPA — not Next.js** | An authenticated dashboard gets no SEO or SSR benefit, and Next.js puts a Node runtime beside Python in every self-hosted install. Static files served from the same container instead |
| Routing | TanStack Router | Type-safe |
| Server state | TanStack Query | — |
| Client state | Zustand | The form builder needs a real store |
| UI | Tailwind + shadcn/ui | Own the components — required for white-labelling |
| Builder DnD | dnd-kit | Nested, accessible |
| Grids | TanStack Table, virtualised | Large record browsing |
| Charts | Recharts, or visx where control is needed | — |
| Maps | MapLibre GL + self-hosted or MapTiler tiles | No licensing trap |
| Realtime | WebSockets / SSE | Live submission feed, sync health |

### 18.4 Web forms runtime — OPEN

Browser-based, self-administered collection (CAWI) is in scope and was missing from the v1.0 draft. Two options:

- **(a)** Compose Multiplatform for Web — literal code reuse, larger bundles, weaker accessibility
- **(b)** Compile the **engine only** to Wasm, render with React — better web UX, one source of truth for logic

**Recommendation: (b).** Resolve in Phase 0 alongside the IR.

---

## 19. Backend module layout

```
backend/
  app/
    api/v1/
    modules/
      auth, organizations, projects, environments
      forms, form_engine, entities, datasets, cases, assignments
      workflows, submissions, reviews, quality, sync, media, gis
      workforce, analytics, notifications, integrations, migration, ai
      devices, audit
    infrastructure/{database, redis, storage, queue, auth, observability}
  workers/
  migrations/
  tests/
```

## 20. Shared KMP module layout

```
shared/
  core/{common, network, database, security, sync, media, location, logging}
  form-engine/{model, ir, compiler, expression, validation, runtime}
  feature/{auth, projects, forms, entities, cases, assignments,
           submissions, review, settings}
  ui/{design-system, components, navigation}
  platform/{android, ios, desktop}
```

| Shared | Platform-specific |
|---|---|
| Domain and use cases | Camera implementation and gallery UI |
| Form IR, compiler, runtime | Location provider |
| Expression and validation | Push notification adapters |
| SQLDelight repositories | Keystore / Keychain |
| Ktor API client | Permissions and background behaviour |
| Sync state machine | Native OS integrations |
| Submission and media metadata | P2P transport |

---

## 21. Database and storage model

Relational tables for identity, ownership, lifecycle, permissions and indexed operational data. JSONB for form definitions and submission payloads. PostGIS for spatial data. Object storage for media and large exports.

**Submission storage pattern:** append-only operation log → materialised current-state JSONB → generated flat view per form version for export and analytics. One table cannot serve all three; do not try.

Core relationships:

```
Organization → Project → Environment → Form → Form Version
Project → Users / Teams → Assignments → Cases → Visits → Submissions → Reviews
Project → Entity Types → Entities → Relationships
Project → Datasets → Dataset Versions → Records
Submission → Media
All significant objects → Audit Events
```

---

## 22. Deployment and self-hosting

| Environment | Approach |
|---|---|
| Development | Docker Compose |
| CI | Lint, unit, integration, build, migration and security tests |
| Staging | Production-like container deployment |
| SaaS production | Managed PostgreSQL, storage and Redis where appropriate |
| Self-hosted | Documented Docker deployment with backup, restore and upgrade tooling |
| Large enterprise | Kubernetes or private cloud when justified |

Backups, restore tests, database migrations, object-storage lifecycle and disaster recovery are mandatory production concerns. Self-hosters will run versions six months old — migrations must be reversible and tested.

---

## 23. Testing strategy

- Form engine unit and conformance tests — the gate for §4
- Property-based tests on expression evaluation
- Cross-platform golden tests
- Sync tests: retries, duplication, ordering, partial connectivity, conflicts, tombstones, snapshot replay
- Offline/online transition tests
- Database migration tests, including downgrade
- Authorization and tenant-isolation tests
- Media upload and resume tests
- Web end-to-end tests
- Real-device Android and iOS tests: camera, GPS, lifecycle, storage
- Load tests: submissions, sync, dashboard queries
- Security and penetration testing before enterprise launch

---

## 24. Non-functional requirements

| Area | Requirement |
|---|---|
| Offline endurance | Every client feature must answer: what happens with no network for 14 days |
| RTL and Arabic | First release, not retrofitted. Affects layout, fonts, number formatting and builder preview |
| Low-end devices | Android 8+, 2GB RAM, 500+ question forms, 50k-row on-device datasets. Test on real cheap hardware |
| Battery | GPS, audio audit and background sync are the three drains — budget them explicitly |
| Accessibility | Screen reader, font scaling, high contrast on clients and console |
| Upgrade safety | Reversible, tested migrations for self-hosted deployments |
| API-first | The console uses the public API; no private endpoints |

---

## 25. Release matrix

| Area | MVP | V1 | V1.5 | V2+ |
|---|---|---|---|---|
| Auth / RBAC | Core | MFA + policy | SSO / OIDC / SAML | Advanced enterprise |
| Form builder | Core | Advanced logic | Advanced widgets | Constrained plugin SDK |
| Question types | Core set | Extended | Matrix, ranking, drawing | Hardware-specific |
| Form IR / runtime | Mandatory | Compatibility expansion | Advanced expressions | Extensions |
| XLSForm / Migration Center | Import + report | Compatibility analyzer | ODK expansion | Migration assistant |
| Web forms (CAWI) | — | Core | Styling, branding | Advanced logic parity |
| Offline | Mandatory | Hardening | Advanced preload | Edge cases |
| Sync | Mandatory | Conflict UI | Optimisation, compaction | Large-scale distribution |
| P2P transfer | Android | iOS | — | — |
| Entities / datasets | Basic | Full model | Advanced relationships | Federation |
| Workflow | Basic review | Full engine | SLA, escalation | Advanced automation |
| GIS | GPS core | Polygons, geofences | Offline maps | Spatial analytics |
| Media | Image, file | Audio, video, signature | Compression tuning | Specialised capture |
| QC / review | Basic + text audit | Full queues, audio audit, speed limits | Anomaly scoring | AI-assisted QC |
| Exports | CSV, XLSX | Stata, SPSS, GeoJSON | Scheduled exports | Warehouse integration |
| Analytics | Operational | Reports, charts, maps | Parquet / DuckDB | Warehouse |
| Workforce | Assignments | Attendance, supervision | Training, messaging | Incentives / payments |
| Device management | Register, revoke | Operational controls | Remote policies | Enterprise fleet |
| Security modes | Standard | Field-level encryption | Project E2EE | HSM / BYOK |
| AI | — | — | Assistive | Advanced |
| Self-hosting | Docker Compose | Production package | Enterprise deployment | Private cloud |

---

## 26. Roadmap

**Phase 0 — Architecture proof (2–3 months).** Form IR specification, expression engine prototype, cross-target conformance suite, sync protocol prototype, ERD, OpenAPI contract, encryption envelope design, iOS Compose spike. *No production builder UI is built in this phase.*

**Phase 1 — MVP (3–4 months).** Auth, tenancy, projects, environments, visual builder, core question types, form versioning, Android offline collection, submissions, sync, GPS and photo, web console, XLSForm import with compatibility report. One real client running one real survey end to end.

**Phase 2 — V1 (4–6 months).** iOS and desktop clients, entities and datasets, cases and visits, assignments, review, workflow engine, media pipeline, monitoring, exports including Stata/SPSS, audit, GIS, web forms.

**Phase 3 — V1.5 (4–6 months).** Conflict UI, analytics, webhooks, SSO/MFA, device management, advanced offline data, workforce module, project E2EE, AI builder and reviewer.

**Phase 4 — V2 (ongoing).** Advanced AI, transcription, incentives/payments, deeper integrations, enterprise and private-cloud capability, SOC 2 evidence.

Realistic parity horizon: **18–30 months**. The plan assumes specific deals are won on specific differentiators long before parity.

---

## 27. Team

| Role | Initial staffing |
|---|---|
| Backend | 2–3 |
| KMP | 2–3 |
| Web | 1–2 |
| QA / automation | 1–2 |
| UI / UX | 1 |
| DevOps | 0.5–1 |
| Product / architecture | 1 |

The critical expertise is form engineering, offline synchronisation, data modelling and security — not UI development.

---

## 28. Decision log

### Locked

| Decision | Answer |
|---|---|
| Backend | Python + FastAPI |
| Backend architecture | Modular monolith |
| Database | PostgreSQL + PostGIS + JSONB |
| Cache / jobs | Redis + workers |
| Storage | S3-compatible (MinIO bundled for self-host) |
| Web console | React + TypeScript + **Vite SPA** (not Next.js) |
| Field shared code | Kotlin Multiplatform |
| Local DB | SQLDelight |
| Networking | Ktor |
| DI | Koin |
| Form representation | Own versioned Form IR (not XForms) |
| Sync | Operation-based, resumable, idempotent, snapshot-capable, tombstoned |
| Workflow | First-class workflow engine |
| Entities | First-class entity / relationship / case / visit model |
| Analytics | PostgreSQL → Parquet / DuckDB |
| Events | Transactional outbox |
| Tenancy | Schema-per-tenant (SaaS); dedicated (enterprise, self-host) |
| Self-hosting | In scope from v1 packaging; a product differentiator, not an ops note |
| Migration Center | Phase 1, customer-facing, with compatibility report |
| Microservices / Kafka / Kubernetes | Deferred until measured need |

### Conditional — resolved by a Phase 0 spike

| Decision | Condition |
|---|---|
| Compose Multiplatform for iOS UI | iOS spike must show acceptable performance and platform feel; SwiftUI over shared core is the fallback, so keep the UI/core boundary strict |

### Closed

| # | Decision | Answer | Decided |
|---|---|---|---|
| O-1 | **First market** | **Survey and research agencies**, with **RCons as the pilot customer**. Decided by which existing relationship signed first, not by market size. Self-hosting, data residency and SSO move back; assignment, supervision and review move forward. §2.3 | 4 Sep 2026 |

### Open — must be answered before Phase 1

| # | Decision | Options | Recommendation |
|---|---|---|---|
| O-2 | **Server-side evaluation** | JVM engine sidecar vs Python port | JVM sidecar |
| O-3 | **Web forms runtime** | Compose Web vs engine-to-Wasm + React | Engine-to-Wasm + React |
| O-4 | **Pricing model** | Per-seat vs per-submission vs flat tiers | Per-seat — attacks the competitor's weakness directly; but it dictates whether metering and quotas are core |
| O-5 | **Open-core** | Fully proprietary vs open-source engine only | Open-source the form engine only: drives adoption and standards credibility, keeps the moat in the server |
| O-6 | **Extensibility** | No plugins vs constrained custom widgets | Constrained widget SDK by V1.5 — without it, every edge case becomes a feature request |

---

## 29. Risks

| Risk | Severity | Mitigation |
|---|---|---|
| Form engine complexity underestimated | Critical | IR + compiler + conformance suite before any broad UI; port ODK's public test cases |
| Sync correctness | Critical | Prototype in Phase 0; idempotency, checkpoints, tombstones, snapshot replay tests |
| Encryption design error | Critical | Established primitives only; envelope design in Phase 0; independent review before enterprise |
| Client/server semantic divergence | High | Resolve O-2; shared conformance suite in CI on every target |
| Switching costs keep customers put | High | Migration Center in Phase 1, treated as a product |
| Feature creep | High | Release matrix plus the out-of-scope list, enforced |
| Cross-platform parity | High | Shared runtime, conformance tests, real-device CI |
| Large datasets and media | High | Pagination, streaming, object storage, analytical projection |
| Compliance blocks enterprise deals | Medium | Start SOC 2 evidence collection in Phase 3, not Phase 4 |
| Team size vs scope | High | Sequence ruthlessly; read ODK Central as a reference implementation (AGPL — read, do not copy) |

---

## 30. Explicitly out of scope

- Full hardware and plugin marketplace
- RFID / NFC / Bluetooth peripheral integrations (V2+ at earliest)
- Payment processing (incentive *tracking* is in scope; disbursement is not)
- Full data warehouse
- Kafka/NATS-first architecture
- Kubernetes-first deployment
- Autonomous AI modification of production forms or data
- Guaranteed automatic conversion of every proprietary competitor feature
- General-purpose BI tooling
- Our own map tile infrastructure

---

## 31. Next engineering artifacts

Phase 0 produces these, in this order:

1. **Form IR Specification** — schema, expression grammar, versioning rules, conformance test format
2. **Sync Protocol Specification** — operation format, checkpoints, conflict rules, tombstones, snapshots
3. **ERD / Database Schema**
4. **Encryption Envelope Specification** — format, key custody, field-level boundary
5. **OpenAPI Contract** (v1)
6. **KMP Module Plan** and **Backend Module Plan**
7. **MVP Acceptance Criteria**

Do not build a production form-builder UI while items 1 and 2 remain unstable.

---

# Appendix A — Feature inventory

Proposed phase per item. Confirm or amend in the scoping session. Phases: **M** = MVP, **1** = V1, **1.5** = V1.5, **2** = V2+.

## A.1 Form authoring

| # | Feature | Phase |
|---|---|---|
| A1 | Visual form builder (web, drag-drop) | M |
| A2 | XLSForm import + compatibility report | M |
| A3 | XLSForm export | 1 |
| A4 | Expression builder UI (no raw XPath) with code escape hatch | M |
| A5 | Form versioning, immutable publish, diff view | M |
| A6 | Preview / test mode with save-resume and real test submissions | M |
| A7 | Explainable logic path in test mode | 1 |
| A8 | Multi-language forms including RTL | M |
| A9 | Form templates library | 1 |
| A10 | Collaborative multi-user editing | 1.5 |
| A11 | Form-level access control (edit vs deploy) | 1 |
| A12 | Pre-publication linting | M |
| A13 | AI form assistant (generate, review, translate) | 1.5 |
| A14 | Data dictionary generation | 1 |

## A.2 Question types

| # | Type | Phase |
|---|---|---|
| Q1 | text, integer, decimal, range | M |
| Q2 | date, time, datetime, Hijri calendar | M |
| Q3 | select_one, select_multiple | M |
| Q4 | Cascading selects | M |
| Q5 | Choice filters from dataset queries | 1 |
| Q6 | Ranking, rating, matrix/grid | 1.5 |
| Q7 | Note / label-only | M |
| Q8 | calculate (hidden computed) | M |
| Q9 | Image capture, annotation, compression | M |
| Q10 | Audio capture | 1 |
| Q11 | Video capture | 1 |
| Q12 | File upload | 1 |
| Q13 | Barcode / QR scan | 1 |
| Q14 | GPS point | M |
| Q15 | GPS trace and shape | 1 |
| Q16 | Signature | 1 |
| Q17 | Free drawing | 1.5 |
| Q18 | NFC / RFID | 2 |
| Q19 | Bluetooth device input (scales, stadiometers, BP) | 2 |
| Q20 | Offline map picker | 1.5 |
| Q21 | Constrained custom widget SDK | 1.5 |

## A.3 Form logic

| # | Feature | Phase |
|---|---|---|
| L1 | Relevance / skip logic | M |
| L2 | Constraints with custom messages | M |
| L3 | Required, including conditional required | M |
| L4 | Defaults, dynamic defaults | M |
| L5 | Repeat groups | M |
| L6 | Nested repeats | 1 |
| L7 | Field lists (multiple questions per screen) | M |
| L8 | Non-linear navigation / jump to question | 1 |
| L9 | Cross-repeat references | 1 |
| L10 | Randomisation of choices and blocks | 1 |
| L11 | Soft constraints with override reason | 1 |
| L12 | Entity / dataset lookup functions | 1 |
| L13 | Server-side expressions on submission | 1 |

## A.4 Clients

| # | Feature | Phase |
|---|---|---|
| C1 | Android app, full offline | M |
| C2 | iOS app, full parity | 1 |
| C3 | Desktop app (Windows/macOS/Linux) | 1 |
| C4 | Web forms (CAWI, browser) | 1 |
| C5 | Save incomplete and resume | M |
| C6 | Encrypted local storage | M |
| C7 | Background upload, retry and resume | M |
| C8 | Configurable media compression | 1 |
| C9 | P2P device-to-device transfer | M (Android) / 1 (iOS) |
| C10 | Multi-project on one device | 1 |
| C11 | PIN / biometric lock | 1 |
| C12 | Offline basemap download per assignment area | 1.5 |
| C13 | Rapid keyboard-driven entry mode (desktop) | 1.5 |
| C14 | Accessibility: screen reader, scaling, contrast | 1 |
| C15 | Sync diagnostics visible to field user | M |

## A.5 Entities, datasets, cases

| # | Feature | Phase |
|---|---|---|
| D1 | Datasets (reference tables attached to forms) | M |
| D2 | Dataset versions, immutable publish | 1 |
| D3 | Incremental dataset sync to device | 1 |
| D4 | Datasets auto-populated from submissions | 1 |
| D5 | Entity types and entities | 1 |
| D6 | Typed relationships between entities | 1 |
| D7 | Cases with status lifecycle | 1 |
| D8 | Visits as collection events against a case | 1 |
| D9 | Case assignment and reassignment | 1 |
| D10 | Form pre-population from case/entity data | 1 |
| D11 | Longitudinal linking across rounds | 1 |
| D12 | Offline case assignment | 1.5 |
| D13 | Geographic / spatial case targeting | 1.5 |
| D14 | Case history timeline and attachments | 1.5 |

## A.6 Workflow

| # | Feature | Phase |
|---|---|---|
| WF1 | Submission review: approve / reject / comment | M |
| WF2 | Workflow definitions: states and transitions | 1 |
| WF3 | Triggers: submission, schedule, quality event, external | 1 |
| WF4 | Actions: notify, assign, approve, webhook, status update | 1 |
| WF5 | Correction loop back to device for re-visit | 1 |
| WF6 | SLA deadlines and escalation | 1.5 |
| WF7 | Offline-safe field transitions | 1.5 |
| WF8 | Advanced automation and branching workflows | 2 |

## A.7 Quality control

| # | Feature | Phase |
|---|---|---|
| QC1 | Text audit (time per question, order, edits) | M |
| QC2 | Audio audit | 1 |
| QC3 | Speed limits (flag or block) | 1 |
| QC4 | GPS / geofence validation | 1 |
| QC5 | Automated quality rules engine on ingest | 1 |
| QC6 | Plausible-range and outlier detection | 1 |
| QC7 | Duplicate and near-duplicate detection | 1 |
| QC8 | Review queues | 1 |
| QC9 | Correction audit trail | 1 |
| QC10 | Back-check / re-interview comparison | 1.5 |
| QC11 | Enumerator scorecards | 1.5 |
| QC12 | Fraud heuristics (patterns, travel speed, off-hours) | 1.5 |
| QC13 | Anomaly scoring and AI-assisted QC | 2 |

## A.8 Analytics and reporting

| # | Feature | Phase |
|---|---|---|
| R1 | Live submission feed | M |
| R2 | Record browser: filter, search, column config | M |
| R3 | Saved views shared across team | 1 |
| R4 | Cross-tabs and summary statistics | 1 |
| R5 | Chart builder | 1 |
| R6 | Map view with clustering | 1 |
| R7 | Field progress vs target tracking | 1 |
| R8 | Custom dashboards | 1.5 |
| R9 | Scheduled email / PDF reports | 1.5 |
| R10 | Tokenised public dashboard sharing | 1.5 |
| R11 | Embeddable widgets | 2 |

## A.9 Workforce operations

| # | Feature | Phase |
|---|---|---|
| W1 | Enumerator roster and team hierarchy | 1 |
| W2 | Assignment routing / territory allocation | 1 |
| W3 | Geofenced check-in / check-out | 1.5 |
| W4 | Attendance and working hours | 1.5 |
| W5 | Supervisor field-visit logging | 1.5 |
| W6 | Field messaging and broadcast | 1.5 |
| W7 | Training and certification tracking | 2 |
| W8 | Incentive / piece-rate calculation | 2 |

## A.10 Security and administration

| # | Feature | Phase |
|---|---|---|
| S1 | RBAC with custom roles | M |
| S2 | Project / workspace isolation | M |
| S3 | Dev / staging / production environments | M |
| S4 | Audit log | 1 |
| S5 | Field-level encryption | 1 |
| S6 | Project-level end-to-end encryption | 1.5 |
| S7 | MFA | 1 |
| S8 | SSO (SAML, OIDC) | 1.5 |
| S9 | Device registration and revocation | 1 |
| S10 | Remote logout and controlled data reset | 1.5 |
| S11 | Data retention policy and hard delete | 1.5 |
| S12 | PII tagging and redaction on export | 1.5 |
| S13 | Self-hosted Docker deployment | 1 |
| S14 | Backup, restore and upgrade tooling | 1 |
| S15 | Multi-region hosting (GCC first) | 1.5 |
| S16 | White-label branding | 2 |
| S17 | SOC 2 readiness | 2 |

## A.11 Data out and integrations

| # | Feature | Phase |
|---|---|---|
| I1 | CSV / XLSX export | M |
| I2 | Stata (.dta) and SPSS (.sav) export | 1 |
| I3 | GeoJSON / KML export | 1 |
| I4 | Wide vs long format for repeats | 1 |
| I5 | Media bundle export | 1 |
| I6 | Scheduled automated exports | 1.5 |
| I7 | REST API with OpenAPI | M |
| I8 | Webhooks | 1 |
| I9 | OpenRosa-compatible ingest endpoint | 1 |
| I10 | Google Sheets sync | 1.5 |
| I11 | Power BI / Tableau connector | 2 |
| I12 | SQL read-replica access | 2 |
| I13 | Zapier / Make | 2 |
| I14 | Customer-owned S3 / Azure media delivery | 2 |

---

# Appendix B — SurveyCTO reference architecture

For comparison when making our own choices.

| Component | Their approach |
|---|---|
| Form definition | W3C XForms subset, authored as XLSForm (survey / choices / settings sheets) |
| Form engine | JavaRosa (Java), XPath expression evaluation |
| Mobile app | SurveyCTO Collect — fork of ODK Collect (Android/Java). iOS added later, weaker parity |
| Web forms | Separate JavaScript engine — the source of their semantic drift |
| Wire protocol | OpenRosa (formList, form download, multipart submission POST) |
| Server | Java, dedicated per-customer AWS instance |
| Submission format | XML instance plus separate media attachments |
| Encryption | Per-submission AES key wrapped with form RSA-2048 public key; private key client-side only |
| Desktop tool | Export, decryption, offline USB sync, form validation |
| Extensibility | Field plugins — HTML/JS bundles in a WebView |
| Datasets | CSV-backed server datasets pulled to device |
| Case management | caseid-keyed dataset plus assignment and form filtering |
| QC | Text audits, audio audits, speed limits, automated quality checks, review workflow |
| Hosting | US, EU, India. No self-hosting |
| Compliance | SOC 2 Type 2, HIPAA, GDPR |
