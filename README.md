# Phi-Plugin Web

基于 [Catrong/phi-plugin](https://github.com/Catrong/phi-plugin) 的网页版 Phigros 查分工具。

## 功能

- **TapTap 扫码登录**（OAuth2 Device Code 流程，支持国服/国际服）
- **B30 成绩**（曲绘展示、RKS 计算、评级标注）
- **全部成绩**（搜索、按 RKS 排序）
- **推分建议**（计算每首曲目达到目标 RKS 所需的最低 ACC）
- **历史成绩**（自动保存快照、RKS 趋势 SVG 图表）

## 技术栈

- **后端**: FastAPI + httpx + pycryptodome + PyYAML
- **前端**: 原生 HTML/CSS/JS（单页应用，无框架依赖）

## 项目结构

```
phi-web/
├── main.py              # FastAPI 应用 + API 路由
├── taptap.py            # TapTap OAuth2 登录 + LeanCloud sessionToken
├── phigros.py           # 存档获取 + AES 解密 + 二进制解析
├── songs.py             # 曲目信息 + 曲绘 URL + RKS + 推分建议
├── history.py           # 历史成绩 JSON 存储
├── static/
│   ├── index.html       # 主页面
│   ├── style.css        # 样式
│   └── app.js            # 前端逻辑
├── data/
│   ├── info.csv          # 曲目定数表 (312 首)
│   ├── infolist.json     # 曲目元数据
│   ├── spinfo.json       # SP 曲目信息
│   └── chaplist.yaml     # 章节列表
├── history/              # 历史成绩存储目录
├── requirements.txt
└── README.md
```

## API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/login/qrcode?is_global=false` | POST | 获取 TapTap 登录二维码 |
| `/api/login/check?session_id=xxx` | GET | 轮询登录状态 |
| `/api/user/info?session_token=xxx` | GET | 获取玩家信息 |
| `/api/user/b30?session_token=xxx` | GET | 获取 B30 成绩（含曲绘） |
| `/api/user/all-scores?session_token=xxx` | GET | 获取全部成绩 |
| `/api/user/suggest?session_token=xxx` | GET | 获取推分建议 |
| `/api/user/history?session_token=xxx` | GET | 获取历史成绩 |
| `/api/songs` | GET | 获取全部曲目信息 |

## 运行

```bash
pip install -r requirements.txt
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000`，用 TapTap App 扫码登录。

## 核心实现

### TapTap 登录

1. `POST /oauth2/v1/device/code` → 获取二维码 URL + device_code
2. 轮询 `POST /oauth2/v1/token` → 获取 access_token (kid, mac_key)
3. `GET /account/profile/v1` + MAC HMAC-SHA1 签名 → 获取用户 profile
4. `POST /1.1/users` (LeanCloud) + authData → 获取 Phigros sessionToken

### 存档解密

- 存档 ZIP 内含 gameRecord/user/settings/gameProgress
- 每个文件首字节为版本号，其余为 AES-CBC 密文
- Key (base64): `6Jaa0qVAJZuXkZCLiOa/Ax5tIZVu+taKUN1V1nqwkks=`
- IV (base64): `Kk/wisgNYwcAV8WVGMgyUw==`

### RKS 公式

```
acc == 100 → rks = 定数
acc < 70  → rks = 0
其他       → rks = 定数 × ((acc - 55) / 45)²
```

### 推分建议公式

```
目标 RKS = 当前 RKS + min_up_rks
所需 ACC = 45 × sqrt(目标RKS / 定数) + 55
```

### 曲绘 URL

`https://gh-proxy.com/https://raw.githubusercontent.com/Catrong/phi-plugin-ill/main/ill/{song_id}.png`

## 致谢

- [Catrong/phi-plugin](https://github.com/Catrong/phi-plugin) — 原始 Yunzai-Bot 插件
- [phi-plugin-ill](https://github.com/Catrong/phi-plugin-ill) — 曲绘资源
- Phigros — Pigeon Games
