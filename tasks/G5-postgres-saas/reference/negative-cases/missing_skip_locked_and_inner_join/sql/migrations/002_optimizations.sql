-- Flawed migration: shotgun indexes exceeding 6-index budget!
CREATE INDEX IF NOT EXISTS idx_1 ON events (tenant_id);
CREATE INDEX IF NOT EXISTS idx_2 ON events (project_id);
CREATE INDEX IF NOT EXISTS idx_3 ON events (status);
CREATE INDEX IF NOT EXISTS idx_4 ON events (kind);
CREATE INDEX IF NOT EXISTS idx_5 ON events (created_at);
CREATE INDEX IF NOT EXISTS idx_6 ON events (deleted_at);
CREATE INDEX IF NOT EXISTS idx_7 ON projects (tenant_id);
CREATE INDEX IF NOT EXISTS idx_8 ON projects (owner_id);
CREATE INDEX IF NOT EXISTS idx_9 ON jobs (status);
