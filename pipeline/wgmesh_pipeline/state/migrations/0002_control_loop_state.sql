-- +migrate Up
-- Control-loop module state: the box's authoritative copy of each planner's
-- returned state dict (supervisor-rank-state, pipeline-health-state,
-- strategy-audit-baseline). The committed company/*.json snapshots become
-- read-only mirrors once a module goes live. JSON-doc rows keyed by module so
-- each cycle can load its previous_state (closing the supervisor
-- "previous_state not loaded" gap). The fingerprint column lets writes dedupe
-- on material change (anti PR-per-run pile-up).
CREATE TABLE IF NOT EXISTS control_loop_state (
  key TEXT PRIMARY KEY,
  fingerprint TEXT NOT NULL DEFAULT '',
  doc TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
