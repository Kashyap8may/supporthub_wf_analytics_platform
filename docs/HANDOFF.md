# Handoff: project state as of 2026-11-10

Read with `CLAUDE.md`. Update this file whenever a milestone finishes or a decision changes.

## Where things stand

| Milestone | Status | Notes |
|---|---|---|
| M0 Scaffold | Done | Tagged `m0` |
| M1 Data generator | Done | Simulation, writers for every source, contracts, 19 tests |
| M2 AWS sources | Next | Share the RetailPulse RDS instance and SFTP server (see decisions) |
| M3 Load the sources | Not started | Reuse RetailPulse's `daily.py` / `publish.py` / bundle patterns |
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

## Notes for M2

- RetailPulse's daily job is being paused (the owner must re-run `databricks auth login` first). Its RDS and EC2 window schedules stay, so the shared servers keep the 06:00 to 08:00 UTC window.
- Shared servers mean SupportHub's Terraform reads RetailPulse's resources (data sources), adds a `supporthub` database and login on RDS, and adds an SFTP user with its own chroot on EC2. Changes to the EC2 user data should go through RetailPulse's Terraform, or SupportHub adds the user via SSM Run Command.
