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
| Staff | About 128: 96 analysts in 8 teams, 10 senior reviewers and 10 QC checkers in 4 teams, and 12 team leads |
| Teams | Each analyst team has skills in order of preference (for example onboarding first, refresh second); Glasgow has a dedicated remediation team, Pune a refresh team that helps with remediation |
| Shifts | Weekdays; Pune 09:30 to 18:30 IST, Glasgow 09:00 to 17:30 UK time; remediation teams work Saturday mornings in the last three weeks before a deadline |
| Shrinkage | Huddles, team meetings, coaching, training, breaks, lunch, booked leave, unplanned absence, attrition and new hires ramping up |
| Volume | About 300 new cases a business day plus a monthly refresh release of 3,600 and remediation tranches, sized so the operation runs close to capacity |

### Case types

| Case type | Inflow | SLA | Handle time | Notes |
|---|---|---|---|---|
| Onboarding (CDD) | ~260 a business day | 2 business days | ~35 min | Monday and month-end peaks, a trickle at weekends |
| Periodic refresh | 3,600 on the first business day of each month | Due date 35 to 75 days later | ~60 min | Builds a backlog wave every month |
| Event-driven (EDD) | ~30 a business day | 5 business days | ~2.5 h | Every case gets QC; a quarter are escalated |
| Remediation | Tranches of 50%, 25%, 25% at weeks 0, 4 and 8 | Project deadline | ~90 min | Three projects of 4,000 to 5,000 cases, each with a deadline and a burndown |

### Case lifecycle

`NEW` → `ASSIGNED` → `IN_PROGRESS` → optionally `PENDING_CUSTOMER` → `ASSIGNED` → `IN_PROGRESS` → optionally `ESCALATED` → `ASSIGNED` → `IN_PROGRESS` → either `CLOSED`, or `QC_PENDING` → `QC_PASSED` → `CLOSED` / `REWORK` → `IN_PROGRESS` → `QC_PENDING`.

Cases go back to `NEW` when an analyst returns them to the queue or a team lead reassigns them because the owner is away. Customers who never respond are closed after 14 days as exit the relationship. Closed cases carry an outcome: approved, rejected, or exit the relationship. Every change is an event with a timestamp, the person who made it and the new assignee.

## Sources

| Source | AWS | Feeds | Pattern |
|---|---|---|---|
| CaseDesk database | RDS PostgreSQL | `case_types`, `queues`, `users`, `remediation_projects`, `cases` (current state, updated in place), `case_events` (append-only status history with assignees) | Incremental on `updated_at` / `event_row_id` |
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
