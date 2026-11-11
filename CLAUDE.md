# SupportHub KYC Operations Analytics: instructions for AI coding assistants

Read this first, then `docs/HANDOFF.md` for the current state and next steps.

## What this project is

A portfolio data engineering project made to look like production. A simulated KYC review operation (SupportHub, about 120 analysts in Pune and Glasgow working cases in a tool called CaseDesk) produces data in four AWS source systems, which feed a Databricks lakehouse (bronze, silver, gold) and a KYC operations health report. The business case, the report questions and the sources are in `README.md`; the detail is in `docs/project-plan.md`.

It follows the same patterns as the owner's earlier project `retailpulse-data-platform` (generator with a fixed calendar and daily change folders, Terraform sources, a publisher run by a Databricks job). Reuse those patterns rather than inventing new ones.

## Ground rules from the owner

- **The owner builds the whole lakehouse and the report (bronze, silver, gold, dashboard; milestones M4 to M9) personally.** Never implement those. Assistants build the generator, the AWS sources, the daily simulator and the data contracts.
- **Everything is synthetic and fictional.** The owner knows this domain from a previous employer. Never use that employer's tool names, queue names, SLA targets, report layouts or data; use generic industry terms and the fictional names in this repo (SupportHub, CaseDesk).
- **Commit at the end of every milestone and update `README.md` every time**, including the Progress table. Milestones are tagged `m0`, `m1`, ...
- **Ask before pushing** to GitHub or opening a pull request.
- **Never put credentials in code, chat or commits.** AWS credentials come from `aws configure`, Databricks from `databricks auth login`, runtime secrets from SSM Parameter Store and a Databricks secret scope.
- Keep generated data out of git (`output/` is ignored).

## Platform constraints

- Databricks is Free Edition: serverless only. It can reach AWS directly over HTTPS and on ports 5432 and 22 (checked for RetailPulse on 2026-10-30).
- AWS region `us-east-1`. Cost matters: stoppable resources, a daily run window, pay-per-request services, and a budget alert.

## Code conventions

- Python 3.11 or newer. Lint and format with ruff (`line-length = 110`), test with pytest. CI runs `ruff check`, `ruff format --check` and `pytest`; keep it green.
- The generator must be deterministic: the same seed gives byte-identical output, and adding a day never changes earlier days. Use `rng_for(seed, ...)` for every random draw.
- Every source feed has a contract in `contracts/`; tests enforce it.
- Comments explain why, not what. Match the style of the surrounding code.
- Keep files with LF line endings (`.gitattributes`).

## Repository map

```
data_generator/
  config.py, reference.py   settings; sites, holidays, case types, queues, teams, remediation projects
  master.py                 staff over the horizon, booked leave, planned_day() (the WFM plan as known on a date)
  simulation.py             the event-driven daily simulation of arrivals, activity and case work
  sources/                  one writer per source + casedesk_schema.sql
  simulate.py               CLI: the whole dataset at one moment
  daily.py                  CLI: one folder of changes per day (uploaded to the simulator bucket)
  publish.py                CLI: applies pending days to the live sources (run daily by the Databricks job)
contracts/                  YAML data contract per feed
services/activity_api/      Lambda handler for the activity tracker API
infra/terraform/            modules/sources and envs/dev (shares RetailPulse's RDS and SFTP server)
infra/scripts/              store-aws-key-in-databricks.ps1
databricks.yml, databricks/ Asset Bundle, the simulator job entry point, connectivity notebook
```
