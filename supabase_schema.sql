-- Supabase 数据库 Schema
-- Phi-Plugin Web 迁移方案
-- 在 Supabase Dashboard → SQL Editor 中执行

-- ===== 用户表 =====
CREATE TABLE IF NOT EXISTS users (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  taptap_openid  TEXT UNIQUE NOT NULL,
  player_name    TEXT DEFAULT '',
  session_token  TEXT NOT NULL,
  is_global      BOOLEAN DEFAULT false,
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

-- ===== B30 历快照表 =====
CREATE TABLE IF NOT EXISTS b30_history (
  id          UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
  save_rks    FLOAT,
  computed_rks FLOAT,
  b30_data    JSONB,          -- 完整 B30 成绩 JSON
  created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ===== 排行榜视图（只读）=====
CREATE OR REPLACE VIEW leaderboard AS
SELECT DISTINCT ON (user_id)
  user_id,
  save_rks,
  computed_rks,
  player_name,
  created_at
FROM b30_history bh
JOIN users u ON bh.user_id = u.id
ORDER BY user_id, created_at DESC;

-- ===== 索引 =====
CREATE INDEX IF NOT EXISTS idx_users_openid ON users(taptap_openid);
CREATE INDEX IF NOT EXISTS idx_history_user ON b30_history(user_id);
CREATE INDEX IF NOT EXISTS idx_history_created ON b30_history(created_at DESC);

-- ===== 启用 RLS（行级安全）=====
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE b30_history ENABLE ROW LEVEL SECURITY;

-- 允许 anon 角色读写（项目本身已有后端鉴权，简化配置）
CREATE POLICY "anon_all_users" ON users FOR ALL TO anon USING (true) WITH CHECK (true);
CREATE POLICY "anon_all_history" ON b30_history FOR ALL TO anon USING (true) WITH CHECK (true);
