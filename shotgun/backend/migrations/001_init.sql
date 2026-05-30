-- Shotgun / Dispatch — Postgres schema (§20)
-- Run with: psql $DATABASE_URL -f migrations/001_init.sql

CREATE TABLE IF NOT EXISTS incidents (
    id text PRIMARY KEY,                     -- inc_01HX… (also the run_id)
    service text,
    symptom text,
    url text,
    repo text,
    commit_sha text,
    severity text,
    status text,                             -- state-machine value
    diagnosis text,
    decision text,                           -- fix | dismiss | null
    pr_url text,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz
);

CREATE TABLE IF NOT EXISTS runs (            -- one row per Kane run
    id text PRIMARY KEY,
    incident_id text REFERENCES incidents(id),
    phase text,                              -- repro | verify | review
    status text,
    attempt int,
    run_dir text,
    replay_url text,
    screenshot text,
    created_at timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS artifacts (
    id serial PRIMARY KEY,
    incident_id text REFERENCES incidents(id),
    kind text,                               -- before_shot|after_shot|before_replay|after_replay|diff
    uri text
);

-- Indexes for dashboard queries
CREATE INDEX IF NOT EXISTS idx_incidents_status ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_created ON incidents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_incident ON runs(incident_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_incident ON artifacts(incident_id);
