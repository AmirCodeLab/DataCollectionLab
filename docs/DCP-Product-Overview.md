---
title: "Data Collection Platform"
subtitle: "Product Overview & Technology Blueprint"
author: "Prepared by AmirCodeLab"
date: "Version 1.0 · August 2026"
---

# 1. Executive summary

The Data Collection Platform (DCP) is an **offline-first platform for field data collection and field operations**. It lets an organisation design a data collection form, assign work to field staff, collect data on phones, tablets, laptops or in a browser without an internet connection, automatically check the quality of what comes back, route it through supervisor review, and analyse the results — all in one system.

Most tools in this market stop at "collect a survey." DCP covers the full operational cycle:

> **assignment → collection → validation → supervision → review → approval → analytics**

The platform consists of four parts that share one common core:

| Part | Who uses it | Where it runs |
|---|---|---|
| **Web console** | Programme managers, supervisors, analysts, administrators | Any modern browser |
| **Field application** | Enumerators, inspectors, field officers | Android, iOS, Windows, macOS, Linux |
| **Web forms** | Survey respondents answering directly | Any browser, via a link |
| **Backend platform** | — | Cloud (managed) or the customer's own servers |

The commercial position is straightforward: the established competitor in this space is SurveyCTO, with KoboToolbox and ODK as the open alternatives. DCP matches their data collection capability, adds an operations and workforce layer they do not have, and can be installed on a customer's own infrastructure — which none of them offer.

---

# 2. The problem we are solving

Organisations that collect data in the field — research agencies, health ministries, NGOs, inspection and audit teams — face the same four problems:

**Connectivity cannot be assumed.** Field staff work in places with no reliable network. Data must be captured, validated and stored locally, then synchronised safely later without loss or duplication.

**Data quality degrades silently.** Without automated checks, errors and fabricated responses are discovered weeks later during analysis, when re-collection is expensive or impossible.

**Collection is only part of the job.** Someone has to assign the work, track who did what, verify it, correct it and approve it. Today this happens in spreadsheets, WhatsApp groups and email alongside the collection tool.

**Data cannot always leave the country.** Many government, health and defence buyers are legally prohibited from using cloud services hosted elsewhere. Existing platforms offer no self-hosted option, which removes them from consideration entirely.

DCP addresses all four as core design constraints rather than add-on features.

---

# 3. Who it is for

| Segment | Typical use | What they need most |
|---|---|---|
| **Survey & research agencies** | Large-scale household surveys, panel studies, market research | Scale, cost control, statistical exports, enumerator supervision |
| **Government & health ministries** | Census, health programmes, facility assessments | Self-hosting, data residency, audit, compliance |
| **NGO / monitoring & evaluation** | Programme monitoring, beneficiary registration, impact evaluation | Ease of use, offline reliability, donor reporting |
| **Enterprise field operations** | Inspections, audits, asset surveys, quality assurance | Workflow, assignment, supervision, integration |
| **Academic research** | Longitudinal studies, randomised trials | Rigorous form logic, encryption, reproducible exports |

---

# 4. How the platform works

## 4.1 End-to-end flow

```
 ┌──────────────┐   ┌─────────────┐   ┌──────────────┐   ┌─────────────┐
 │ 1. DESIGN    │──►│ 2. ASSIGN   │──►│ 3. COLLECT   │──►│ 4. SYNC     │
 │ Build form   │   │ Create      │   │ Offline on   │   │ Upload when │
 │ Test & publish│  │ cases,      │   │ phone/tablet/│   │ connectivity│
 │              │   │ allocate to │   │ desktop or   │   │ returns     │
 │              │   │ field staff │   │ browser      │   │             │
 └──────────────┘   └─────────────┘   └──────────────┘   └──────┬──────┘
                                                                │
 ┌──────────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────▼──────┐
 │ 8. ANALYSE   │◄──│ 7. APPROVE  │◄──│ 6. REVIEW    │◄──│ 5. VALIDATE │
 │ Dashboards,  │   │ Close case  │   │ Supervisor   │   │ Automated   │
 │ reports,     │   │ or send for │   │ checks       │   │ quality     │
 │ exports      │   │ correction  │   │ flagged work │   │ checks      │
 └──────────────┘   └─────────────┘   └──────────────┘   └─────────────┘
```

## 4.2 System architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  FIELD CLIENTS                                                   │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌──────────────────┐   │
│  │ Android │  │   iOS   │  │ Desktop │  │ Web form (browser)│   │
│  └────┬────┘  └────┬────┘  └────┬────┘  └────────┬─────────┘   │
│       └────────────┴────────────┴────────────────┘              │
│              SHARED CORE (Kotlin Multiplatform)                  │
│     form engine · sync engine · local database · encryption      │
└──────────────────────────┬──────────────────────────────────────┘
                           │  secure, resumable synchronisation
┌──────────────────────────▼──────────────────────────────────────┐
│  BACKEND PLATFORM  (Python / FastAPI)                            │
│  identity · forms · entities · cases · workflow · quality        │
│  sync · media · analytics · integrations · audit                 │
└───┬──────────────┬──────────────┬───────────────┬───────────────┘
    │              │              │               │
┌───▼─────┐  ┌─────▼──────┐ ┌─────▼──────┐ ┌──────▼────────┐
│PostgreSQL│  │ Object     │ │ Redis      │ │ Background    │
│ + PostGIS│  │ storage    │ │ cache/queue│ │ workers       │
└──────────┘  └────────────┘ └────────────┘ └───────────────┘

┌─────────────────────────────────────────────────────────────────┐
│  WEB CONSOLE  (React + TypeScript)                               │
│  form builder · dashboards · cases · review · admin · reports    │
└─────────────────────────────────────────────────────────────────┘
```

## 4.3 The single shared engine

The most important technical decision in the platform: **the form logic engine is written once and runs everywhere.**

When a form says "only ask about pregnancy if the respondent is female and aged 15–49," that rule must behave identically on an Android phone, an iPhone, a laptop, in a browser and on the server. Competing platforms maintain separate engines for mobile and web, and those engines drift apart over time — producing the situation where the same form behaves differently depending on the device.

DCP compiles every form into one internal representation and evaluates it with one engine, shared across all targets. An automated conformance suite must pass identically on every platform before any release.

---

# 5. What makes DCP different

| # | Differentiator | Why it matters |
|---|---|---|
| 1 | **One form engine on every platform** | Identical behaviour on Android, iOS, desktop, web and server — no device-dependent surprises |
| 2 | **Self-hosting as a first-class product** | Install on the customer's own servers. Opens government, defence and regulated health markets that cloud-only platforms cannot serve |
| 3 | **Operations, not just collection** | A real workflow engine with assignment, SLAs, escalation and correction loops — not an approval button bolted onto a submission list |
| 4 | **Transparent, resumable synchronisation** | Data uploads field-by-field and resumes after interruption, instead of all-or-nothing submissions that fail on weak networks |
| 5 | **Analytics that replace the export** | Dashboards, cross-tabs, charts and maps in the platform, so teams stop exporting to external tools for basic monitoring |
| 6 | **Workforce management built in** | Assignment routing, geofenced attendance, supervision and incentive tracking — currently run on spreadsheets |
| 7 | **Migration is a product feature** | Import existing forms from competitors with an explicit compatibility report, lowering the cost of switching |

---

# 6. Features — web console

The web console is the management surface used by programme managers, supervisors and analysts.

## 6.1 Form design

- **Visual form builder** with drag-and-drop question ordering, groups and repeat sections
- **Spreadsheet import** — bring existing XLSForm and ODK forms in, with a compatibility report showing exactly what converted and what needs attention
- **Logic builder** for skip logic, validation rules and calculations, with a visual condition editor and a code view for advanced users
- **Version control** — published versions are frozen; every submission records which version produced it
- **Test mode** with save-and-resume, real test submissions, and an *explainable logic path* showing why each question appeared, was skipped or was calculated
- **Multi-language forms**, including full right-to-left support for Arabic and Urdu
- **Templates library** for common survey types
- **Data dictionary** generated automatically for every project
- **AI assistance** for drafting forms, reviewing logic and producing translations — always requiring human approval

## 6.2 Project and user management

- Organisations, projects and teams with role-based permissions
- Custom roles with fine-grained access control
- Development, staging and production environments per project, so changes are tested before reaching live fieldwork
- Multi-factor authentication and single sign-on (SAML / OIDC)
- Full audit log of administrative, security and data events

## 6.3 Cases, entities and assignments

- **Entity model** for real-world structures — Household → Members → Plots → Crops, or Facility → Staff → Equipment
- **Reference datasets** uploaded or generated from previous submissions, used to pre-populate forms
- **Cases** with a status lifecycle, and **visits** as individual collection events against a case
- Assignment and reassignment to individuals or teams, including bulk and geographic assignment
- Longitudinal linking, connecting responses across survey rounds back to the same respondent

## 6.4 Workflow and review

- Configurable workflow states and transitions per project
- Triggers on submission, schedule, quality event or external system
- Actions: notify, assign, approve, reject, create task, call an external system
- Review queues showing exactly which quality flags were raised
- Comment, correct, approve or reject; rejections push the task back to the field worker's device for a return visit
- SLA deadlines with automatic escalation
- Complete correction history — who changed what, when and why

## 6.5 Data quality and monitoring

- **Automated quality rules** run on every incoming submission
- **Text audits** — time spent per question, navigation order, number of edits
- **Audio audits** — random or triggered background recording to verify interviews were properly administered
- **Speed limits** — flag or block submissions completed implausibly fast
- **Location validation** — was the submission taken inside the assigned area
- **Statistical checks** — duplicates, near-duplicates, outliers, implausible values
- **Fraud detection** — identical answer patterns, impossible travel speed between submissions, off-hours activity
- **Enumerator scorecards** — completion rate, flag rate, average duration, rejection rate
- Back-check and re-interview comparison reports

## 6.6 Analytics and reporting

- Live submission feed as data arrives
- Record browser with filtering, search and configurable columns over large datasets
- Saved views shared across the team
- Cross-tabulations and summary statistics
- Chart builder — bar, line, distribution and comparison charts
- Map view with clustering and geographic filtering
- Progress against target tracking by area, team or enumerator
- Custom dashboards assembled from widgets
- Scheduled email and PDF reports
- Shareable read-only dashboards for donors and external stakeholders

## 6.7 Data export and integration

- Export to CSV, Excel, **Stata (.dta)**, **SPSS (.sav)**, GeoJSON and KML
- Wide and long formats for repeating sections
- Media bundle export
- Scheduled automated exports
- Full REST API with published OpenAPI documentation
- Webhooks on submission and status change
- Google Sheets synchronisation and business intelligence connectors

## 6.8 Device and security administration

- Device registry with last sync, app version, storage and operational health
- Remote logout, device revocation and controlled data reset
- Force or recommend synchronisation; require app update
- Encryption settings per project, including field-level encryption of sensitive data
- Data retention policies and PII tagging for export redaction

---

# 7. Features — field application

The field application runs on Android, iOS and desktop from a single shared codebase. Everything below works with **no internet connection**.

## 7.1 Data capture

| Category | Supported |
|---|---|
| Text and numeric | Short text, long text, integer, decimal, ranges |
| Date and time | Date, time, datetime, Hijri calendar |
| Choices | Single select, multi select, cascading selects, dataset-filtered choices, ranking, rating, matrix grids |
| Media | Photo with annotation, audio, video, file attachment, signature, free drawing |
| Location | GPS point, path (line), area (polygon), map picker on offline basemaps |
| Scanning | Barcode and QR code |
| Computed | Hidden calculations, auto-captured metadata |

## 7.2 Form behaviour

- Skip logic and conditional questions
- Validation with clear error messages, plus "soft" warnings the enumerator can override with a stated reason
- Automatic calculations
- Repeating sections, including nested repeats
- Multiple questions per screen where appropriate
- Non-linear navigation — jump between sections
- Randomisation of answer options and question blocks for research designs
- Full multi-language switching mid-interview, including right-to-left layouts

## 7.3 Offline operation

- Forms, assigned cases, reference datasets and maps cached on the device
- All logic, validation and calculation run locally — no round trip to a server
- Drafts saved automatically; interviews can be paused and resumed
- Outbox showing exactly what is waiting to upload
- Background upload that resumes automatically after interruption, rather than restarting
- Media compressed on the device before upload, with configurable quality
- Encrypted local storage; the device holds no readable data if lost
- PIN or biometric lock on the application
- **Peer-to-peer transfer** — move submissions, cases and assignments directly between two devices with no internet at all, so one device reaching connectivity can sync for a whole team

## 7.4 Field workflow

- List of assigned cases with status, priority and location
- Case history — what was collected on previous visits
- Forms pre-populated from earlier rounds and reference data
- Geofenced check-in and check-out for attendance
- Tasks pushed back from supervisors for correction and re-visit
- Messages and broadcasts from the project team
- Clear, readable sync status — what has uploaded, what has not, and why

## 7.5 Field-facing quality

- Real-time validation as the enumerator types
- Plausible-range warnings on measurements
- Duplicate detection against already-collected records
- GPS accuracy indication before a location is accepted
- Automatic capture of interview duration and question timing

---

# 8. Features — web forms

For self-administered surveys where there is no interviewer:

- Distributed by a simple link, with no login required
- Same form logic as the mobile application — one engine, no behavioural differences
- Save and resume partially completed responses
- Mobile-responsive layout
- Optional branding
- Partial response capture, so incomplete submissions still yield usable data

---

# 9. Core workflows

## 9.1 Form lifecycle

```
Design (builder, import or AI draft)
   → Compile and lint → Test with explainable logic path
   → Publish to Development → Staging → Production
   → Version frozen · devices receive update
   → Historical submissions keep their original version
```

## 9.2 Collection and synchronisation

```
Assignment reaches device  →  Offline interview  →  Saved locally
   →  Finalised and encrypted  →  Queued in outbox
   →  Uploaded incrementally when connectivity returns (resumes if interrupted)
   →  Server validates against the exact form version used
```

## 9.3 Quality and review

```
Submission received
   → Automated quality checks run
       ├─ clean      → low-priority queue or auto-approval by policy
       └─ flagged    → supervisor review queue with the specific flags shown
   → Supervisor comments, corrects, approves or rejects
   → Rejection → task returns to the field worker's device for re-visit
   → Every change recorded with actor, time and reason
```

## 9.4 Migration from an existing platform

```
Upload existing form  →  Compatibility analysis
   →  Report: fully supported / partially supported / unsupported
   →  Convert  →  Preview  →  Test with sample data
   →  Approve  →  Deploy to Development environment
```

---

# 10. Technology stack

## 10.1 Backend platform

| Layer | Technology | Purpose |
|---|---|---|
| Language | Python 3.12+ | Core backend services |
| API framework | FastAPI | REST API with automatically generated documentation |
| Data validation | Pydantic | Request and response schemas |
| Database access | SQLAlchemy + Alembic | Data layer and versioned schema migrations |
| Background processing | Celery + Redis | Quality checks, exports, reports, webhooks |
| Architecture | Modular monolith | Lower operational complexity; services extracted only when justified |

## 10.2 Data and storage

| Layer | Technology | Purpose |
|---|---|---|
| Primary database | PostgreSQL 16 | Projects, forms, cases, submissions, workflow, audit |
| Spatial engine | PostGIS | Geofencing, spatial assignment, map queries |
| Analytics | Parquet + DuckDB | Dashboard aggregates and reporting without loading the main database |
| Cache and queue | Redis | Sessions, rate limiting, job queue |
| Object storage | S3-compatible (MinIO for self-hosted) | Photos, audio, video, attachments, exports |

## 10.3 Web console

| Layer | Technology | Purpose |
|---|---|---|
| Framework | React 19 + TypeScript | Console application |
| Build | Vite (single-page application) | Static output — keeps self-hosted installs simple |
| Styling | Tailwind CSS + component library | Interface, theming and white-labelling |
| Data tables | Virtualised grid | Browsing very large submission sets |
| Charts | Recharts / visx | Dashboards and reports |
| Maps | MapLibre GL | Submission maps, geofence drawing |
| Form builder | dnd-kit | Drag-and-drop question and group ordering |
| Realtime | WebSockets | Live submission feed and sync status |

## 10.4 Field applications

| Layer | Technology | Purpose |
|---|---|---|
| Shared codebase | Kotlin Multiplatform | One codebase for Android, iOS and desktop |
| User interface | Compose Multiplatform | Shared field interface across all three |
| Local database | SQLDelight | Offline storage of forms, cases, drafts and media metadata |
| Networking | Ktor | Communication with the backend |
| Dependency injection | Koin | Application composition |
| Local encryption | SQLCipher + platform keystores | Encrypted device storage |
| Maps | MapLibre Native | Offline basemaps and location capture |
| Background sync | WorkManager (Android) / BGTaskScheduler (iOS) | Reliable upload without the app open |
| Peer-to-peer | Nearby Connections / MultipeerConnectivity | Device-to-device transfer with no internet |

## 10.5 Infrastructure and operations

| Layer | Technology | Purpose |
|---|---|---|
| Packaging | Docker | Identical image for cloud and self-hosted |
| Self-hosted deployment | Docker Compose | Single-command install with backup and upgrade tooling |
| Cloud orchestration | Kubernetes (when scale requires) | Managed production environments |
| CI/CD | GitHub Actions | Build, test and cross-platform conformance checks |
| Monitoring | OpenTelemetry, Grafana, Sentry | Traces, metrics, logs and client error reporting |

---

# 11. Security and compliance

DCP is designed for organisations handling personal, health and identifying data.

**Three security modes** are available per project:

| Mode | Description | Typical use |
|---|---|---|
| **Standard** | Data encrypted in transit and at rest, queryable by authorised users | Most operational projects |
| **Field-level encryption** | Named sensitive fields encrypted individually; the rest stays queryable so dashboards and quality checks continue to work | Health, financial and identifying data |
| **End-to-end encryption** | Data encrypted on the device and decryptable only by the key holder — never readable by the server or the platform operator | Ethics-board and IRB-governed research |

Additional controls:

- Role-based access control with least-privilege defaults
- Multi-factor authentication and enterprise single sign-on
- Complete, immutable audit trail
- Device registration, revocation and remote data reset
- Short-lived access tokens and signed media URLs
- Encrypted local storage on every device
- Data retention policies and personal-data tagging
- Dependency, container and secret scanning in the build pipeline
- Independent security review and penetration testing before enterprise rollout

---

# 12. Deployment options

| Option | Description | Suited to |
|---|---|---|
| **Managed cloud** | We host and operate the platform; customer chooses a region | Most commercial customers |
| **Dedicated cloud** | Isolated database and infrastructure for a single customer | Large enterprise, sensitive programmes |
| **Self-hosted** | Installed on the customer's own servers with documented backup, restore and upgrade tooling | Government, defence, regulated health, data-residency requirements |

Self-hosting is a supported product, not a special arrangement — the same Docker image runs in all three configurations.

---

# 13. Delivery roadmap

| Phase | Focus | Outcome |
|---|---|---|
| **Phase 0** — Foundations | Form engine, synchronisation protocol, data model, security design | Proven technical core, validated across all platforms |
| **Phase 1** — MVP | Form builder, Android collection, submissions, web console, form import | One live client running one real survey end to end |
| **Phase 2** — Version 1 | iOS and desktop, cases and entities, workflow, review, media, statistical exports, web forms | Full replacement for existing tools in the primary market |
| **Phase 3** — Version 1.5 | Analytics, workforce module, device management, single sign-on, end-to-end encryption | Enterprise and government readiness |
| **Phase 4** — Version 2 | Advanced AI, incentives, deeper integrations, compliance certification | Scale and enterprise expansion |

The first engineering milestone deliberately proves the form engine and synchronisation protocol before any large user interface is built. These are the two components on which everything else depends.

---

# 14. Glossary

| Term | Meaning |
|---|---|
| **Enumerator** | A field worker who conducts interviews or collects data |
| **Form** | A structured questionnaire with questions, logic and validation |
| **Form version** | A frozen, published snapshot of a form; submissions record which one they used |
| **Submission** | One completed set of answers from one interview or inspection |
| **Entity** | A real-world thing being tracked — a household, patient, facility, asset |
| **Case** | A unit of assigned work relating to an entity |
| **Visit** | A single collection event against a case; a case can have many visits |
| **Dataset** | Reference data used to pre-populate or validate forms |
| **Synchronisation** | Exchanging data between a device and the server, incrementally and resumably |
| **Text audit** | A record of how long each question took and in what order it was answered |
| **Audio audit** | A background recording used to verify an interview was properly conducted |
| **XLSForm** | A widely used spreadsheet standard for defining forms, supported for import |
| **Offline-first** | Designed so that no feature depends on connectivity being present |
| **CAPI / CAWI** | Computer-assisted personal / web interviewing |
