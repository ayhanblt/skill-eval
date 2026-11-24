-- 002_optimizations.sql: 4 targeted indexes (covering keyset, project-scoped active, pending job queue, RLS) + cached initPlan RLS policies

-- 1. Partial covering composite index for keyset pagination AND Index Only Scan feed summaries
CREATE INDEX IF NOT EXISTS events_active_tenant_keyset_idx
  ON events (tenant_id, created_at DESC, id DESC)
  INCLUDE (project_id, kind)
  WHERE deleted_at IS NULL AND status = 'active';

-- 2. Partial composite index with leading project_id for LEFT JOIN summaries and project-scoped queries
CREATE INDEX IF NOT EXISTS events_active_project_idx
  ON events (project_id, created_at DESC)
  WHERE deleted_at IS NULL AND status = 'active';

-- 3. Partial index for non-blocking SKIP LOCKED job worker queue
CREATE INDEX IF NOT EXISTS jobs_pending_priority_idx
  ON jobs (priority DESC, created_at ASC, id ASC)
  WHERE status = 'pending';

-- 4. Composite index supporting RLS tenant + private owner filtering on projects
CREATE INDEX IF NOT EXISTS projects_tenant_visibility_idx
  ON projects (tenant_id, is_private, owner_id, id);

-- Optimize RLS policies by wrapping current_setting() inside (SELECT ...) initPlan
DROP POLICY IF EXISTS projects_tenant_policy ON projects;
CREATE POLICY projects_tenant_policy ON projects
  FOR ALL
  TO app_user
  USING (
    tenant_id = (SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
    AND (
      NOT is_private
      OR owner_id = (SELECT NULLIF(current_setting('app.current_user_id', true), '')::bigint)
    )
  )
  WITH CHECK (
    tenant_id = (SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
  );

DROP POLICY IF EXISTS events_tenant_policy ON events;
CREATE POLICY events_tenant_policy ON events
  FOR ALL
  TO app_user
  USING (
    tenant_id = (SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
  )
  WITH CHECK (
    tenant_id = (SELECT NULLIF(current_setting('app.current_tenant_id', true), '')::bigint)
  );
