PRAGMA foreign_keys = ON;

CREATE TABLE party (
    party_id                TEXT PRIMARY KEY,
    full_name               TEXT NOT NULL,
    party_type              TEXT NOT NULL CHECK (party_type IN ('client', 'opposing_party')),
    national_id_or_reg_no   TEXT,
    email                   TEXT,
    phone                   TEXT,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE staff (
    staff_id     TEXT PRIMARY KEY,
    full_name    TEXT NOT NULL,
    role         TEXT NOT NULL CHECK (role IN ('receptionist', 'senior_associate', 'partner', 'admin')),
    email        TEXT NOT NULL UNIQUE,
    active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1))
);

CREATE TABLE case_type_policy (
    policy_id                TEXT PRIMARY KEY,
    case_type                TEXT NOT NULL CHECK (case_type IN ('civil', 'criminal', 'corporate', 'family', 'IP')),
    min_seniority_required   INTEGER NOT NULL,
    required_documents       TEXT,   -- JSON array, e.g. ["national_id", "poa"]
    auto_reject_if_conflict  INTEGER NOT NULL DEFAULT 0 CHECK (auto_reject_if_conflict IN (0, 1))
);

CREATE TABLE lawyer (
    lawyer_id         TEXT PRIMARY KEY,
    full_name         TEXT NOT NULL,
    bar_number        TEXT NOT NULL UNIQUE,
    specialization    TEXT NOT NULL,
    seniority_level   TEXT NOT NULL CHECK (seniority_level IN ('junior', 'associate', 'senior', 'partner')),
    current_caseload  INTEGER NOT NULL DEFAULT 0,
    max_caseload      INTEGER NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'on_leave', 'inactive'))
);

CREATE TABLE batch_job (
    job_id            TEXT PRIMARY KEY,
    triggered_by      TEXT NOT NULL REFERENCES staff(staff_id),
    job_type          TEXT NOT NULL CHECK (job_type IN ('bulk_conflict_check', 'other')),
    total_items       INTEGER NOT NULL DEFAULT 0,
    processed_items   INTEGER NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed')),
    started_at        TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at      TEXT
);

CREATE TABLE "case" (
    case_id            TEXT PRIMARY KEY,
    client_party_id    TEXT NOT NULL REFERENCES party(party_id),
    policy_id          TEXT NOT NULL REFERENCES case_type_policy(policy_id),
    description        TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'submitted' CHECK (
                            status IN (
                                'submitted', 'conflict_check_pending', 'conflict_clear',
                                'conflict_flagged', 'under_review', 'accepted',
                                'rejected', 'assigned'
                            )
                        ),
    estimated_value    REAL,
    jurisdiction       TEXT,
    decision_reason    TEXT,
    decided_by         TEXT REFERENCES staff(staff_id),
    decision_at        TEXT,
    submitted_at       TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE document (
    document_id     TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES "case"(case_id),
    file_name       TEXT NOT NULL,
    file_type       TEXT NOT NULL,
    storage_path    TEXT NOT NULL,
    upload_status   TEXT NOT NULL DEFAULT 'pending' CHECK (upload_status IN ('pending', 'verified', 'missing')),
    uploaded_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE conflict_check (
    check_id           TEXT PRIMARY KEY,
    case_id            TEXT NOT NULL REFERENCES "case"(case_id),
    batch_job_id       TEXT REFERENCES batch_job(job_id),       -- nullable
    matched_party_id   TEXT REFERENCES party(party_id),          -- nullable
    match_type         TEXT NOT NULL CHECK (match_type IN ('exact_match', 'fuzzy_name_match', 'related_party')),
    confidence_score   REAL NOT NULL DEFAULT 0,
    resolution         TEXT NOT NULL DEFAULT 'unresolved' CHECK (resolution IN ('unresolved', 'confirmed_conflict', 'false_positive')),
    resolved_by        TEXT REFERENCES staff(staff_id),          -- nullable
    checked_at         TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE case_assignment (
    assignment_id   TEXT PRIMARY KEY,
    case_id         TEXT NOT NULL REFERENCES "case"(case_id),
    lawyer_id       TEXT NOT NULL REFERENCES lawyer(lawyer_id),
    assigned_by     TEXT NOT NULL REFERENCES staff(staff_id),
    role_on_case    TEXT NOT NULL CHECK (role_on_case IN ('lead', 'support')),
    assigned_at     TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE audit_log (
    log_id           TEXT PRIMARY KEY,
    actor_staff_id   TEXT NOT NULL REFERENCES staff(staff_id),
    action           TEXT NOT NULL,
    entity_type      TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    outcome          TEXT NOT NULL CHECK (outcome IN ('success', 'denied', 'error')),
    timestamp        TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_case_client_party ON "case"(client_party_id);
CREATE INDEX idx_case_status ON "case"(status);
CREATE INDEX idx_conflict_check_case ON conflict_check(case_id);
CREATE INDEX idx_conflict_check_batch ON conflict_check(batch_job_id);
CREATE INDEX idx_case_assignment_case ON case_assignment(case_id);
CREATE INDEX idx_case_assignment_lawyer ON case_assignment(lawyer_id);
CREATE INDEX idx_audit_log_entity ON audit_log(entity_type, entity_id);

CREATE TABLE graph_checkpoint(
    checkpoint_id           TEXT PRIMARY KEY,
    thread_id               TEXT NOT NULL,
    checkpoint_ns           TEXT NOT NULL DEFAULT '',
    parent_checkpoint_id    TEXT,
    checkpoint_type         TEXT NOT NULL,
    checkpoint_data         BLOB NOT NULL,
    metadata_type           TEXT NOT NULL,
    metadata_data           BLOB NOT NULL,
    created_at              TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_graph_checkpoint_thread
    ON graph_checkpoint(thread_id, checkpoint_ns);

CREATE TABLE graph_checkpoint_write (
    thread_id               TEXT NOT NULL,
    checkpoint_ns           TEXT NOT NULL DEFAULT '',
    checkpoint_id           TEXT NOT NULL,
    task_id                 TEXT NOT NULL,
    task_path               TEXT NOT NULL DEFAULT '',
    write_index             INTEGER NOT NULL,
    channel                 TEXT NOT NULL,
    value_type              TEXT NOT NULL,
    value_data              BLOB NOT NULL,

    PRIMARY KEY (
        thread_id,
        checkpoint_ns,
        checkpoint_id,
        task_id,
        task_path,
        write_index
    )
);

CREATE TABLE hitl_tasks (
    task_id              TEXT PRIMARY KEY,
    thread_id            TEXT NOT NULL,
    case_id              TEXT NOT NULL REFERENCES "case"(case_id),
    task_type            TEXT NOT NULL,
    risk_score           REAL NOT NULL,
    status               TEXT NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'approved', 'rejected')),
    decision_by          TEXT REFERENCES staff(staff_id),
    decision_at          TEXT,
    created_at           TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at           TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_hitl_tasks_thread
    ON hitl_tasks(thread_id);

CREATE INDEX idx_hitl_tasks_status
    ON hitl_tasks(status);


CREATE TABLE tickets (
    ticket_id      TEXT PRIMARY KEY,
    case_id        TEXT NOT NULL REFERENCES "case"(case_id),
    thread_id      TEXT NOT NULL,
    checkpoint_id  TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    error_message  TEXT NOT NULL,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    resolved_by    TEXT REFERENCES staff(staff_id),
    resolved_at    TEXT
);

CREATE INDEX idx_tickets_thread ON tickets(thread_id);
CREATE INDEX idx_tickets_status ON tickets(status);