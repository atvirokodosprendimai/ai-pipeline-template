CREATE TABLE IF NOT EXISTS issues (
  number INTEGER PRIMARY KEY,
  title TEXT NOT NULL,
  classification TEXT,
  stage TEXT NOT NULL DEFAULT 'queued',
  status TEXT NOT NULL DEFAULT 'open',
  risk_tier TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  spec_pr INTEGER,
  impl_pr INTEGER,
  last_error TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  issue INTEGER NOT NULL,
  node TEXT NOT NULL,
  started TEXT NOT NULL,
  ended TEXT,
  outcome TEXT NOT NULL,
  langsmith_run_id TEXT,
  tokens INTEGER,
  FOREIGN KEY(issue) REFERENCES issues(number)
);

CREATE INDEX IF NOT EXISTS idx_issues_claim
  ON issues(stage, status, updated_at);

CREATE INDEX IF NOT EXISTS idx_runs_issue
  ON runs(issue, started);

