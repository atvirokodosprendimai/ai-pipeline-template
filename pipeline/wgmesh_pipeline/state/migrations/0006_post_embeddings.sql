-- +migrate Up
-- Per-post embedding cache for semantic dedup (U2).
--
-- The forge dedup compares a candidate's embedding against every board post's.
-- Re-embedding the whole board on each create is wasteful (worse under a restart
-- storm), so each post's vector is computed once and cached here, keyed by post
-- id + model. A model change is a cache miss (the key includes the model), so an
-- EMBEDDINGS_MODEL bump invalidates stale vectors rather than comparing across
-- incompatible spaces.
CREATE TABLE IF NOT EXISTS post_embeddings (
  post_id TEXT PRIMARY KEY,
  model TEXT NOT NULL,
  vector TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
