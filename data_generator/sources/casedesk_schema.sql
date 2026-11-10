-- CaseDesk case management database (source 1, RDS PostgreSQL).
-- cases is updated in place; case_events is the append-only history.

CREATE SCHEMA IF NOT EXISTS casedesk;
SET search_path TO casedesk;

CREATE TABLE IF NOT EXISTS case_types (
    case_type_code  varchar(4)   PRIMARY KEY,
    case_type_name  varchar(60)  NOT NULL,
    queue_code      varchar(10)  NOT NULL,
    sla_days        integer,
    created_at      timestamptz  NOT NULL,
    updated_at      timestamptz  NOT NULL
);

CREATE TABLE IF NOT EXISTS queues (
    queue_code      varchar(10)  PRIMARY KEY,
    queue_name      varchar(60)  NOT NULL,
    case_type_code  varchar(4)   REFERENCES case_types (case_type_code),
    created_at      timestamptz  NOT NULL,
    updated_at      timestamptz  NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    employee_id   varchar(10)   PRIMARY KEY,
    display_name  varchar(120)  NOT NULL,
    email         varchar(160)  NOT NULL,
    is_active     boolean       NOT NULL,
    created_at    timestamptz   NOT NULL,
    updated_at    timestamptz   NOT NULL
);

CREATE TABLE IF NOT EXISTS remediation_projects (
    project_id    varchar(10)   PRIMARY KEY,
    project_name  varchar(120)  NOT NULL,
    start_date    date          NOT NULL,
    deadline      date          NOT NULL,
    scope_cases   integer       NOT NULL,
    created_at    timestamptz   NOT NULL,
    updated_at    timestamptz   NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    case_id                 bigint PRIMARY KEY,
    case_ref                varchar(20)  NOT NULL UNIQUE,
    case_type_code          varchar(4)   NOT NULL REFERENCES case_types (case_type_code),
    queue_code              varchar(10)  NOT NULL REFERENCES queues (queue_code),
    remediation_project_id  varchar(10)  REFERENCES remediation_projects (project_id),
    customer_ref            varchar(12)  NOT NULL,
    customer_segment        varchar(10)  NOT NULL,
    risk_tier               varchar(6)   NOT NULL,
    priority                varchar(6)   NOT NULL,
    status                  varchar(20)  NOT NULL,
    assignee_employee_id    varchar(10)  REFERENCES users (employee_id),
    created_at              timestamptz  NOT NULL,
    due_at                  timestamptz  NOT NULL,
    closed_at               timestamptz,
    outcome                 varchar(20),
    updated_at              timestamptz  NOT NULL
);

CREATE TABLE IF NOT EXISTS case_events (
    event_row_id          bigint PRIMARY KEY,
    event_id              varchar(12)  NOT NULL,
    case_id               bigint       NOT NULL REFERENCES cases (case_id),
    event_type            varchar(24)  NOT NULL,
    from_status           varchar(20),
    to_status             varchar(20)  NOT NULL,
    assignee_employee_id  varchar(10),
    actor_employee_id     varchar(10),
    outcome               varchar(20),
    event_ts              timestamptz  NOT NULL,
    recorded_at           timestamptz  NOT NULL
);

-- Indexes that support incremental extraction.
CREATE INDEX IF NOT EXISTS ix_cases_updated_at         ON cases (updated_at);
CREATE INDEX IF NOT EXISTS ix_case_events_recorded_at  ON case_events (recorded_at);
CREATE INDEX IF NOT EXISTS ix_case_events_case         ON case_events (case_id);
