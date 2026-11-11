# Handoff: project state as of 2026-11-10

Read with `CLAUDE.md`. Update this file whenever a milestone finishes or a decision changes.

## Where things stand

| Milestone | Status | Notes |
|---|---|---|
| M0 Scaffold | Done | Tagged `m0` |
| M1 Data generator | Done | Simulation, writers for every source, contracts, 19 tests |
| M2 AWS sources | Done 2026-11-11 | 69 resources; every source tested from a laptop |
| M3 Load the sources | Done 2026-11-11 | History 2026-06-30 to 2026-11-10 published and checked; daily job `supporthub-source-simulator` at 06:15 UTC |
| M4 to M9 | Owner's own work | Do not implement |

## How the generator works

- `master.py` decides everything about people over the fixed 365-day horizon: hires, leavers and their replacements, team moves, booked leave (with the date it was booked, so late bookings miss the published schedule), and `planned_day()`, the WFM plan of a person on a day as known on a given date.
- `simulation.py` runs each day: arrivals, actual activity built from the plan, then an event-driven run of the workforce (a heap of people by next free time; per-queue heaps by priority and due date; personal queues for work that returns to its owner). Handle times are lognormal, scaled by personal speed and new-hire ramp-up.
- `sources/` writes each system as it looks at `as_of`. Cases are rebuilt from events up to `as_of`; the activity API hides end times after `as_of`; files appear once their publish time has passed. That makes the M3 daily split straightforward: one day's changes are what changes between two `as_of` moments.
- Tests prove determinism, that adding a day never changes earlier days, consistent case histories, that nobody starts work outside productive time, and that every feed matches its contract.

## Decisions made

| Decision | Choice | Why |
|---|---|---|
| Domain | KYC review back office, not a contact centre | Matches the owner's WFM experience; work arrives as cases in a tool, not calls |
| Names | SupportHub (company), CaseDesk (case tool) | Fictional; nothing from the owner's former employer |
| Size | About 128 staff in Pune and Glasgow, 12 teams | Close to capacity, so backlog, SLA and burndown have something to show |
| Case types | Onboarding (CDD), periodic refresh, event-driven (EDD), remediation | Chosen by the owner |
| Workflow | Pending customer info, QC 4-eyes check with rework, escalation, reassignment | Chosen by the owner |
| Report | Backlog and ageing, SLA and turnaround, productivity and AHT, capacity and quality, remediation burndown calculator, analyst performance | Chosen by the owner |
| Remediation | Tranches at weeks 0, 4 and 8; one dedicated team plus a team that helps when its refresh queue is clear | Gives a non-trivial burndown: REM-01 misses its deadline by about three weeks, REM-02 starts behind |
| Infrastructure | Share the RetailPulse RDS instance (new database) and SFTP server (new chrooted user) | Owner's choice: about $1 a month extra instead of $5 to $8 |

## M2 as built

- RetailPulse's daily job is paused (2026-11-10); its RDS and EC2 window schedules stay, so the shared servers run 06:00 to 08:00 UTC.
- Terraform state is in RetailPulse's state bucket under the key `supporthub/dev/sources.tfstate`.
- The `cyrilgdn/postgresql` provider creates the database, roles, schema and grants with the shared instance's admin login (read from `/retailpulse/dev/postgres/*`), so **the RDS instance must be running for every plan and apply.**
- The SFTP user is added by an SSM association running `AWS-RunShellScript` on the shared instance; it re-runs when the instance comes online and is idempotent. The server's sshd already chroots every `sftponly` member.
- The `pipelines` policy is a managed policy: as an inline user policy its parameter allow-list exceeded the 2,048-character limit, which failed the first apply.
- Smoke test on 2026-11-11: owner creates tables, reader reads but cannot write, non-TLS refused, RetailPulse's logins refused, API 200/403/400, SFTP chroot holds, buckets reachable.
- Tested from Databricks serverless on 2026-11-11 with the `pipelines` key from the `supporthub-dev` secret scope: S3, restricted parameters refused, API, CaseDesk through psycopg and Spark JDBC, SFTP.

## M3 as built

- `data_generator/daily.py` writes one folder per day (366 for the year, 280 MB, uploaded to `s3://<simulator bucket>/days/`). `tests/test_daily.py` proves that replaying them rebuilds `generate()` for CaseDesk, the activity API and every file.
- `data_generator/publish.py` follows RetailPulse's publisher; the tables are created by the owner login, so Terraform's default privileges give the reader SELECT automatically.
- The Databricks job `supporthub-source-simulator` (bundle `databricks.yml`) runs at 06:15 UTC with the `simulator` key. The first catch-up (134 days) took 4 minutes; every source then matched the day folders exactly.
- RetailPulse's scheduled runs did not fire on some days (4, 5 and 10 November); watch the run history here. A missed run is harmless, since the next one catches up.
- The calendar ends on 2027-06-30. To go further, raise `horizon_days`, regenerate, re-upload and republish from scratch.

## Next steps

1. Owner: M4 onwards (lakehouse and report). Everything the pipelines need is in the README section "Reading the sources".
2. Watch the first scheduled runs of `supporthub-source-simulator`.
