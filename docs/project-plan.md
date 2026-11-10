# Project plan

## Scope

- A simulated KYC review operation (SupportHub) with four AWS source systems: a relational case management database, a REST API, an S3 file drop and an SFTP server.
- A daily feed: the sources hold history and receive the next day's changes every morning, as live systems do.
- Ingestion into Databricks with Unity Catalog, schemas `bronze`, `silver` and `gold`, and a KYC operations health dashboard.
- Bronze, silver, gold and the dashboard are built by the project owner. The sources, the simulator and the data contracts are built first.

## The simulated operation

| Item | Value |
|---|---|
| Sites | Pune (Asia/Kolkata, no DST) and Glasgow (Europe/London, BST in summer), each with its own public holidays |
| Staff | ~120: about 95 analysts, 10 senior reviewers (escalations), 10 QC checkers, 8 team leads |
| Teams | 8 teams of 12 to 15, each skilled for a subset of case types |
| Shifts | Weekdays; Pune 09:30 to 18:30 IST, Glasgow 09:00 to 17:30 UK time; overtime on some Saturdays before remediation deadlines |
| Shrinkage | Meetings, training, coaching, breaks, leave, sickness, attrition and new hires ramping up |
| Volume | About 600 to 700 new cases a business day, sized to fit the staffing |

### Case types

| Case type | Daily inflow | SLA | Handle time | Notes |
|---|---|---|---|---|
| Onboarding (CDD) | ~300 | 2 business days | ~40 min | Spikes on Mondays and month-ends |
| Periodic refresh | ~200 | Due date by risk tier | ~70 min | Released in monthly batches ahead of the due date |
| Event-driven (EDD) | ~40 | 5 business days | ~3 h | Random arrivals, higher escalation rate |
| Remediation | planned batches | Project deadline | ~75 min | Two or three projects with a fixed scope, a deadline and a burndown |

### Case lifecycle

`NEW` → `ASSIGNED` → `IN_PROGRESS` → (`PENDING_CUSTOMER` ↔ `IN_PROGRESS`) → (`ESCALATED` → `IN_PROGRESS`) → `QC_PENDING` → `QC_PASSED` → `CLOSED`, or `QC_FAILED` → `REWORK` → `QC_PENDING`.

Cases can also be `REASSIGNED` or `RETURNED_TO_QUEUE` at most steps. Closed cases carry an outcome: approved, rejected, or exit the relationship. Every change is an event with a timestamp and the analyst who made it.

## Sources

| Source | AWS | Feeds | Pattern |
|---|---|---|---|
| CaseDesk database | RDS PostgreSQL | `case_types`, `queues`, `cases` (current state, updated in place), `case_events` (append-only status history), `case_assignments` | Incremental on `updated_at` / event id |
| Activity tracker | API Gateway + Lambda + DynamoDB | Analyst state segments (start, end, state, source device login) | `GET /activities?updated_since=` with paging |
| HR and QC | S3 | `hr/roster/extract_date=YYYY-MM-DD/roster.csv` (full daily snapshot), `qc/results/date=YYYY-MM-DD/*.json` | Auto Loader |
| WFM planning | SFTP | Weekly volume forecasts per case type and day, published schedules per analyst and day (re-published when they change), remediation project plans | SFTP pull |

### Data problems built in on purpose

| Source | Problem | What the pipeline must do |
|---|---|---|
| CaseDesk | Cases are updated in place; status history is a separate event table | Rebuild the lifecycle from events; time in each status |
| CaseDesk | Some events arrive late or twice | Deduplicate on event id; order by event time, not load time |
| CaseDesk | SLA clocks stop while pending customer information and count business days by site | Build a business-day calendar per site and an SLA clock that pauses |
| Activity tracker | Identifies analysts by network login, not HR employee id; overlapping and open-ended segments | Map logins through the HR roster; split and cap segments |
| HR roster | Full daily snapshot; team moves, leavers and hires | SCD Type 2 from snapshots |
| QC results | Sampled, not every case; some results land a day late | Join on case and attempt; handle late arrivals |
| WFM | Schedules are re-published when they change | Keep the latest version per analyst and day, and the history |
| WFM | Forecasts come in weekly versions | Compare actuals with the forecast that was current at the time |
| All | Two time zones, one with DST | Store UTC plus site-local dates |

## Target gold model (owner's design)

| Fact | Grain | Main sources |
|---|---|---|
| fact_case | one case | CaseDesk |
| fact_case_status_interval | one stretch of time a case spent in one status | CaseDesk events |
| fact_analyst_activity_daily | one analyst per day per activity state | Activity tracker, HR roster |
| fact_schedule_daily | one analyst per scheduled day | WFM schedules |
| fact_forecast_daily | one case type per day per forecast version | WFM forecasts |
| fact_qc_result | one QC check | QC results |
| fact_remediation_burndown | one remediation project per day | CaseDesk, WFM project plans |

Dimensions: date → week → month, site → country, analyst (SCD2) → team → site, case type → work stream, queue, case status, activity state, risk tier.

## Milestones

Each milestone ends with a commit, a git tag (`m0`, `m1`, ...) and an update to the progress table in the README.

| Milestone | Delivers |
|---|---|
| M0 Scaffold | Repo layout, README, plan, CI skeleton |
| M1 Data generator | Seeded simulation of the operation, writers for every source, data contracts, tests |
| M2 AWS sources | Terraform for RDS, the activity API, S3, SFTP, parameters, IAM, budget alert |
| M3 Load the sources | Day folders for a year, history published, daily Databricks job |
| M4 Databricks foundation | Catalogs, schemas, secret scope (owner) |
| M5 Bronze | One ingestion job per source (owner) |
| M6 Silver | Lifecycle, SLA clock, ID mapping, SCD2, quarantine (owner) |
| M7 Gold | Snowflake model and measures (owner) |
| M8 Orchestration and ops | End-to-end workflow, alerts, audit table (owner) |
| M9 Showcase | Dashboard, burndown calculator, screenshots, write-up (owner) |
