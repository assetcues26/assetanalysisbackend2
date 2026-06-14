-- SaaS extended: web drafts + activity feed

CREATE TABLE IF NOT EXISTS saas_web_drafts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  title             TEXT,
  draft_json        JSONB NOT NULL DEFAULT '{}',
  asset_image_path  TEXT,
  barcode_image_path TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS saas_activity_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  event_type  TEXT NOT NULL,
  asset_id    UUID REFERENCES saas_registered_assets(id) ON DELETE SET NULL,
  assetname   TEXT,
  assetid     TEXT,
  ai_status   TEXT,
  message     TEXT NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_saas_web_drafts_user_updated
  ON saas_web_drafts (user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_saas_activity_user_created
  ON saas_activity_events (user_id, created_at DESC);

DROP TRIGGER IF EXISTS saas_web_drafts_updated_at ON saas_web_drafts;
CREATE TRIGGER saas_web_drafts_updated_at
  BEFORE UPDATE ON saas_web_drafts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE saas_web_drafts ENABLE ROW LEVEL SECURITY;
ALTER TABLE saas_activity_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS saas_web_drafts_demo_all ON saas_web_drafts;
CREATE POLICY saas_web_drafts_demo_all ON saas_web_drafts
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

DROP POLICY IF EXISTS saas_activity_events_demo_all ON saas_activity_events;
CREATE POLICY saas_activity_events_demo_all ON saas_activity_events
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);
