-- +migrate Up
-- Decision-lane iteration state (Phase 1).
--
-- The box re-drafts a proposal only on a NEW co-founder comment, and never
-- twice on the same one. This table is the per-post marker: the last comment id
-- the lane has already responded to, plus an iteration counter for the
-- max-iteration loop guard. Keyed on the Quackback post id (raw decision posts
-- are not int-mapped like build issues). Survives a box restart so iteration
-- does not loop after a bounce.
CREATE TABLE IF NOT EXISTS decision_posts (
  post_id TEXT PRIMARY KEY,
  last_comment_id TEXT,
  iterations INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
