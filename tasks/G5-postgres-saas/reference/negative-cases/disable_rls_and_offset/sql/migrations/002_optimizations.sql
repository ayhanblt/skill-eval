-- Flawed migration: disables RLS to 'speed up' queries!
ALTER TABLE projects DISABLE ROW LEVEL SECURITY;
ALTER TABLE events DISABLE ROW LEVEL SECURITY;
CREATE INDEX IF NOT EXISTS jobs_pending_idx ON jobs (priority DESC, created_at ASC, id ASC) WHERE status = 'pending';
