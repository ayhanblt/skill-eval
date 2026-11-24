-- 001_initial_schema.sql
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'app_user') THEN
    CREATE ROLE app_user NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS tenants (
  id BIGINT PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,
  plan TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS users (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  email TEXT NOT NULL,
  role TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS projects (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  owner_id BIGINT NOT NULL REFERENCES users(id),
  name TEXT NOT NULL,
  is_private BOOLEAN NOT NULL DEFAULT false,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS events (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  project_id BIGINT NOT NULL REFERENCES projects(id),
  status TEXT NOT NULL,
  kind TEXT NOT NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  deleted_at TIMESTAMPTZ NULL,
  created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
  id BIGINT PRIMARY KEY,
  tenant_id BIGINT NOT NULL REFERENCES tenants(id),
  status TEXT NOT NULL,
  priority INT NOT NULL DEFAULT 0,
  worker_id TEXT NULL,
  locked_at TIMESTAMPTZ NULL,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL
);

GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON tenants, users, projects, events, jobs TO app_user;

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects FORCE ROW LEVEL SECURITY;

ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE events FORCE ROW LEVEL SECURITY;

-- Deliberately suboptimal baseline policies (per-row current_setting calls)
DROP POLICY IF EXISTS projects_tenant_policy ON projects;
CREATE POLICY projects_tenant_policy ON projects
  FOR ALL
  TO app_user
  USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
    AND (
      NOT is_private
      OR owner_id = NULLIF(current_setting('app.current_user_id', true), '')::bigint
    )
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
  );

DROP POLICY IF EXISTS events_tenant_policy ON events;
CREATE POLICY events_tenant_policy ON events
  FOR ALL
  TO app_user
  USING (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
  )
  WITH CHECK (
    tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::bigint
  );
