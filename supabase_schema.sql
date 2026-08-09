-- Phi-Plugin Web Supabase Schema (彻底迁移版)
-- 在 Supabase Dashboard → SQL Editor 执行

-- ===== 用户表 =====
CREATE TABLE IF NOT EXISTS users (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  taptap_openid TEXT UNIQUE NOT NULL,
  player_name   TEXT DEFAULT '',
  avatar_url    TEXT DEFAULT '',
  session_token TEXT NOT NULL,
  is_global     BOOLEAN DEFAULT false,
  created_at    TIMESTAMPTZ DEFAULT NOW(),
  updated_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 存档表 (替代 LeanCloud gamesaves) =====
CREATE TABLE IF NOT EXISTS archives (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
  game_record   JSONB,          -- 完整 gameRecord 解析数据
  summary       JSONB,          -- 存档 summary (rks, 段位等)
  game_user     JSONB,          -- 游戏内 user 信息
  b30_data      JSONB,          -- B30 成绩列表 (计算后)
  save_rks      FLOAT,          -- 存档 RKS
  computed_rks  FLOAT,          -- 计算 RKS
  total_songs   INT DEFAULT 0,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ===== B30 历史快照 (趋势用) =====
CREATE TABLE IF NOT EXISTS b30_history (
  id            UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id       UUID REFERENCES users(id) ON DELETE CASCADE,
  save_rks      FLOAT,
  computed_rks  FLOAT,
  b30_data      JSONB,
  created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 排行榜视图 =====
CREATE OR REPLACE VIEW leaderboard AS
SELECT DISTINCT ON (a.user_id)
  a.user_id,
  a.save_rks,
  a.computed_rks,
  u.player_name,
  a.created_at
FROM archives a
JOIN users u ON a.user_id = u.id
ORDER BY a.user_id, a.created_at DESC;

-- ===== 索引 =====
CREATE INDEX IF NOT EXISTS idx_users_openid ON users(taptap_openid);
CREATE INDEX IF NOT EXISTS idx_users_token ON users(session_token);
CREATE INDEX IF NOT EXISTS idx_archives_user ON archives(user_id);
CREATE INDEX IF NOT EXISTS idx_archives_created ON archives(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_history_user ON b30_history(user_id);

-- ===== RLS =====
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE archives ENABLE ROW LEVEL SECURITY;
ALTER TABLE b30_history ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_all" ON users FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon_all" ON archives FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon_all" ON b30_history FOR ALL TO anon USING (true) WITH CHECK (true);
