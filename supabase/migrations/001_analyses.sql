-- Asset Lens analysis persistence (demo user_id = 100)
-- Run in Supabase SQL Editor for project byftlfblysvlmqpcqfnu

CREATE TABLE IF NOT EXISTS analyses (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  entry_id        TEXT NOT NULL UNIQUE,
  user_id         INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  request_id      TEXT NOT NULL UNIQUE,
  asset_name      TEXT,
  asset_tag       TEXT,
  condition_grade TEXT,
  analysis_method TEXT,
  processing_mode TEXT,
  images_analyzed INTEGER NOT NULL DEFAULT 0,
  processed_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  result_json     JSONB NOT NULL,
  collage_path    TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analysis_images (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  analysis_id   UUID NOT NULL REFERENCES analyses(id) ON DELETE CASCADE,
  user_id       INTEGER NOT NULL DEFAULT 100 CHECK (user_id = 100),
  sort_order    INTEGER NOT NULL CHECK (sort_order >= 1),
  storage_path  TEXT NOT NULL UNIQUE,
  file_name     TEXT,
  mime_type     TEXT NOT NULL DEFAULT 'image/jpeg',
  byte_size     INTEGER,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (analysis_id, sort_order)
);

CREATE INDEX IF NOT EXISTS idx_analyses_user_processed ON analyses (user_id, processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_analyses_request_id ON analyses (request_id);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS analyses_updated_at ON analyses;
CREATE TRIGGER analyses_updated_at
  BEFORE UPDATE ON analyses
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

ALTER TABLE analyses ENABLE ROW LEVEL SECURITY;
ALTER TABLE analysis_images ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS analyses_demo_read ON analyses;
CREATE POLICY analyses_demo_read ON analyses
  FOR SELECT USING (user_id = 100);

DROP POLICY IF EXISTS analyses_demo_write ON analyses;
CREATE POLICY analyses_demo_write ON analyses
  FOR INSERT WITH CHECK (user_id = 100);

DROP POLICY IF EXISTS analyses_demo_update ON analyses;
CREATE POLICY analyses_demo_update ON analyses
  FOR UPDATE USING (user_id = 100);

DROP POLICY IF EXISTS analyses_demo_delete ON analyses;
CREATE POLICY analyses_demo_delete ON analyses
  FOR DELETE USING (user_id = 100);

DROP POLICY IF EXISTS analysis_images_demo_all ON analysis_images;
CREATE POLICY analysis_images_demo_all ON analysis_images
  FOR ALL USING (user_id = 100) WITH CHECK (user_id = 100);

-- Storage bucket: create "analysis-images" as PRIVATE in Supabase Dashboard
-- (Storage UI — not creatable via plain SQL on all plans)
-- Allowed MIME: image/jpeg, image/png, image/webp
-- Max object size: 20 MB
