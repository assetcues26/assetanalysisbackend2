-- SaaS asset register tables in public schema (PostgREST-compatible without extra schema exposure)
-- Run in Supabase SQL Editor if not using setup_supabase.py

CREATE TABLE IF NOT EXISTS saas_registered_assets (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  assetid         TEXT NOT NULL,
  assetname       TEXT,
  description     TEXT,
  tagnumber       TEXT,
  assetnumber     TEXT,
  assetclassid    TEXT,
  assetclassname  TEXT,
  categoryid      TEXT,
  categoryname    TEXT,
  subcategoryid   TEXT,
  subcategoryname TEXT,
  makemodelid     TEXT,
  makemodelname   TEXT,
  companyid       TEXT,
  company         TEXT,
  customerid      TEXT,
  assettaggingdetailid TEXT,
  cost            NUMERIC(14,2),
  acquisitiondate TEXT,
  asset_image_path TEXT,
  barcode_image_path TEXT,
  ai_status       TEXT NOT NULL DEFAULT 'pending'
                  CHECK (ai_status IN ('pending','analyzing','pass','fail','error')),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, assetid)
);

CREATE TABLE IF NOT EXISTS saas_asset_analyses (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  asset_id              UUID NOT NULL REFERENCES saas_registered_assets(id) ON DELETE CASCADE,
  user_id               INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  request_id            TEXT,
  response_json         JSONB NOT NULL,
  ai_status             TEXT NOT NULL CHECK (ai_status IN ('pass','fail','error')),
  failure_summary       JSONB,
  response_time_seconds NUMERIC(8,2),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saas_asset_create_sessions (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  session_token     TEXT NOT NULL UNIQUE,
  user_id           INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  status            TEXT NOT NULL DEFAULT 'active'
                    CHECK (status IN ('active','images_ready','completed','expired')),
  draft_json        JSONB NOT NULL DEFAULT '{}',
  asset_image_path  TEXT,
  barcode_image_path TEXT,
  created_asset_id  UUID REFERENCES saas_registered_assets(id),
  expires_at        TIMESTAMPTZ NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_saas_reg_assets_user_created
  ON saas_registered_assets (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_reg_assets_ai_status
  ON saas_registered_assets (ai_status);
CREATE INDEX IF NOT EXISTS idx_saas_asset_analyses_asset
  ON saas_asset_analyses (asset_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_create_sessions_token
  ON saas_asset_create_sessions (session_token);

DROP TRIGGER IF EXISTS saas_registered_assets_updated_at ON saas_registered_assets;
CREATE TRIGGER saas_registered_assets_updated_at
  BEFORE UPDATE ON saas_registered_assets
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS saas_asset_create_sessions_updated_at ON saas_asset_create_sessions;
CREATE TRIGGER saas_asset_create_sessions_updated_at
  BEFORE UPDATE ON saas_asset_create_sessions
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE saas_registered_assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas_asset_analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas_asset_create_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS saas_registered_assets_demo_all ON saas_registered_assets;
CREATE POLICY saas_registered_assets_demo_all ON saas_registered_assets
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

DROP POLICY IF EXISTS saas_asset_analyses_demo_all ON saas_asset_analyses;
CREATE POLICY saas_asset_analyses_demo_all ON saas_asset_analyses
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

DROP POLICY IF EXISTS saas_asset_create_sessions_demo_all ON saas_asset_create_sessions;
CREATE POLICY saas_asset_create_sessions_demo_all ON saas_asset_create_sessions
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);
