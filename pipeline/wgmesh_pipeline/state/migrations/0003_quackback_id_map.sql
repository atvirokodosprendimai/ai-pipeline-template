-- +migrate Up
-- Store-backed Quackback post-id -> int mapping (KTD6/OQ3).
--
-- The Forge protocol is int-keyed, but Quackback post ids are opaque strings
-- (post_...). The AUTOINCREMENT `number` is the stable int that threads into
-- issues.number, bot/impl-{n} branch names, and resolution-PR title matching,
-- replacing the in-memory dict in QuackbackForge so the mapping survives a box
-- restart. Idempotency keys on (quackback_post_id, accept_marker): a re-accept
-- (changed marker) re-queues the SAME number; an already-seen marker is a no-op.
CREATE TABLE IF NOT EXISTS quackback_posts (
  number INTEGER PRIMARY KEY AUTOINCREMENT,
  quackback_post_id TEXT NOT NULL UNIQUE,
  accept_marker TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
