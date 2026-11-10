# Handoff: project state as of 2026-11-10

Read with `CLAUDE.md`. Update this file whenever a milestone finishes or a decision changes.

## Where things stand

| Milestone | Status | Notes |
|---|---|---|
| M0 Scaffold | Done | README, plan, CI skeleton |
| M1 Data generator | Next | See the plan for the operation, case types, lifecycle and data problems |
| M2 to M3 | Not started | Reuse the RetailPulse Terraform, daily-folder generator and publisher patterns |
| M4 to M9 | Owner's own work | Do not implement |

## Decisions made

| Decision | Choice | Why |
|---|---|---|
| Domain | KYC review back office, not a contact centre | Matches the owner's WFM experience; work arrives as cases in a tool, not calls |
| Names | SupportHub (company), CaseDesk (case tool) | Fictional; nothing from the owner's former employer |
| Size | ~120 staff, Pune and Glasgow, ~600 to 700 new cases a business day | Volumes sized so the staffing can work them at realistic handle times |
| Case types | Onboarding (CDD), periodic refresh, event-driven (EDD), remediation | Chosen by the owner |
| Workflow | Pending customer info, QC 4-eyes check with rework, escalation, reassignment | Chosen by the owner |
| Report | Backlog and ageing, SLA and turnaround, productivity and AHT, capacity and quality, remediation burndown calculator, analyst performance | Chosen by the owner |
| Sources | CaseDesk on RDS PostgreSQL, activity tracker API, HR and QC drops on S3, WFM exports on SFTP | Four source types, as in RetailPulse |

## Open questions

1. **Share the RetailPulse AWS servers?** Recommended: a second database on the same RDS instance and a second chrooted SFTP user on the same EC2 server, adding about $1 a month instead of $5 to $8 for a separate stack. The catch is that the two projects then depend on each other's infrastructure.
