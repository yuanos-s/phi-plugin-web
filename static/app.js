// Phi-Plugin Web — 前端逻辑 (Supabase 增强版)
let selectedGlobal = false;
let loginSessionId = null;
let pollTimer = null;
let countdownTimer = null;
let sessionToken = null;
let isGlobal = false;
let currentTab = 'b30';
let cachedUserId = null;      // Supabase user_id
let cachedPlayerName = '';
let sbEnabled = false;

// ===== 主题 =====
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme');
  const next = cur === 'light' ? '' : 'light';
  if (next) document.documentElement.setAttribute('data-theme', next);
  else document.documentElement.removeAttribute('data-theme');
  localStorage.setItem('theme', next || 'dark');
  $('.theme-toggle').textContent = next === 'light' ? '☀️' : '🌙';
}
(function loadTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  if (saved === 'light') {
    document.documentElement.setAttribute('data-theme', 'light');
    document.addEventListener('DOMContentLoaded', () => {
      const t = $('.theme-toggle'); if (t) t.textContent = '☀️';
    });
  }
})();

// ===== 页面加载时检查自动登录 =====
(async function autoLogin() {
  const savedToken = localStorage.getItem('session_token');
  const savedUid = localStorage.getItem('user_id');

  // 先获取配置
  try {
    const r = await fetch('/api/config');
    const d = await r.json();
    sbEnabled = d.supabase_enabled;
  } catch(e) { sbEnabled = false; }

  if (!savedToken) {
    // 没有缓存 token，直接显示登录页
    $('#login-card-main').style.display = 'block';
    return;
  }

  // 检查缓存的 token 是否有效
  $('#login-checking').style.display = 'block';
  try {
    const r = await fetch('/api/auth/restore?session_token=' + encodeURIComponent(savedToken));
    const d = await r.json();
    if (d.status === 'ok') {
      // 自动登录成功
      sessionToken = d.session_token;
      isGlobal = d.is_global;
      cachedUserId = d.user_id || savedUid || null;
      cachedPlayerName = d.player_name || '';
      $('#login-checking').style.display = 'none';
      $('#login-page').style.display = 'none';
      $('#dashboard').style.display = 'block';
      switchTab('b30');
    } else {
      // Token 失效，清除缓存，显示登录页
      localStorage.removeItem('session_token');
      localStorage.removeItem('user_id');
      $('#login-checking').style.display = 'none';
      $('#login-card-main').style.display = 'block';
      if (d.status === 'expired') {
        $('#login-status').textContent = '登录已过期，请重新扫码';
      }
    }
  } catch(e) {
    $('#login-checking').style.display = 'none';
    $('#login-card-main').style.display = 'block';
  }
})();

// ===== Login =====
function selectServer(g) {
  selectedGlobal = g;
  $('#cn-btn').classList.toggle('active', !g);
  $('#gb-btn').classList.toggle('active', g);
}

async function startLogin() {
  $('#login-status').textContent = '正在获取二维码...';
  $('#login-status').classList.remove('error');
  $('#login-btn').disabled = true;
  try {
    const r = await fetch('/api/login/qrcode?is_global=' + selectedGlobal, {method:'POST'});
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || '请求失败');
    loginSessionId = d.session_id;

    $('#qr-img-el').src = 'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data=' + encodeURIComponent(d.qr_url);
    $('#qr-img').style.display = 'block';
    $('#qr-ph').style.display = 'none';
    $('#login-status').textContent = '请使用 TapTap App 扫描二维码';
    $('#login-btn').textContent = '重新获取';
    $('#login-btn').disabled = false;
    startCountdown(d.expires_in || 300);

    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollLogin, 2500);
  } catch(e) {
    $('#login-status').textContent = '获取失败: ' + e.message;
    $('#login-status').classList.add('error');
    $('#login-btn').disabled = false;
  }
}

function startCountdown(seconds) {
  let remain = seconds;
  if (countdownTimer) clearInterval(countdownTimer);
  const update = () => {
    if (remain <= 0) {
      clearInterval(countdownTimer); countdownTimer = null;
      $('#qr-countdown').textContent = '二维码已过期';
      if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
      $('#login-btn').disabled = false;
      $('#qr-img').style.display = 'none';
      $('#qr-ph').style.display = 'flex';
      return;
    }
    const m = Math.floor(remain / 60), s = remain % 60;
    $('#qr-countdown').textContent = `⏱ ${m}:${s.toString().padStart(2,'0')}`;
    remain--;
  };
  update();
  countdownTimer = setInterval(update, 1000);
}

async function pollLogin() {
  if (!loginSessionId) return;
  try {
    const r = await fetch('/api/login/check?session_id=' + loginSessionId);
    // BUG #10: 404/500 时停止轮询，不再被 catch 吞掉
    if (r.status === 404) {
      clearInterval(pollTimer); pollTimer = null;
      clearInterval(countdownTimer); countdownTimer = null;
      $('#login-status').textContent = '登录会话已过期，请重新获取二维码';
      $('#login-status').classList.add('error');
      $('#login-btn').disabled = false;
      loginSessionId = null;
      $('#qr-img').style.display = 'none';
      $('#qr-ph').style.display = 'flex';
      return;
    }
    if (r.status >= 500) {
      // 服务器错误，不停止轮询，但提示
      $('#login-status').textContent = '⚠️ 服务器暂时不可用，正在重试...';
      $('#login-status').classList.add('error');
      return;
    }
    const d = await r.json();

    if (d.status === 'waiting') {
      $('#login-status').textContent = '等待扫码...';
    } else if (d.status === 'scanned') {
      $('#login-status').textContent = '✅ 已扫描，请在 TapTap 中确认登录';
    } else if (d.status === 'success') {
      clearInterval(pollTimer); pollTimer = null;
      clearInterval(countdownTimer); countdownTimer = null;
      sessionToken = d.session_token;
      isGlobal = d.is_global;
      cachedUserId = d.user_id || null;
      cachedPlayerName = d.player_name || '';
      localStorage.setItem('session_token', sessionToken);
      localStorage.setItem('is_global', isGlobal);
      if (cachedUserId) localStorage.setItem('user_id', cachedUserId);
      $('#login-status').textContent = '✅ 登录成功！正在跳转...';
      setTimeout(() => {
        $('#login-page').style.display = 'none';
        $('#dashboard').style.display = 'block';
        switchTab('b30');
      }, 600);
    } else if (d.status === 'expired') {
      clearInterval(pollTimer); pollTimer = null;
      clearInterval(countdownTimer); countdownTimer = null;
      $('#login-status').textContent = '⏰ 二维码已过期，请重新获取';
      $('#login-status').classList.add('error');
      $('#login-btn').disabled = false;
      $('#qr-img').style.display = 'none';
      $('#qr-ph').style.display = 'flex';
    } else if (d.status === 'error') {
      $('#login-status').textContent = '⚠️ ' + (d.message || '错误');
      $('#login-status').classList.add('error');
    }
  } catch(e) {
    // 网络错误，不停止轮询，继续重试
  }
}

function logout() {
  sessionToken = null; isGlobal = false; cachedUserId = null;
  if (pollTimer) clearInterval(pollTimer);
  if (countdownTimer) clearInterval(countdownTimer);
  localStorage.removeItem('session_token');
  localStorage.removeItem('user_id');
  $('#dashboard').style.display = 'none';
  $('#login-page').style.display = 'flex';
  $('#login-card-main').style.display = 'block';
  $('#login-btn').disabled = false;
  $('#login-btn').textContent = '获取二维码';
  $('#login-status').textContent = '';
  $('#login-status').classList.remove('error');
  $('#qr-countdown').textContent = '';
  $('#qr-img').style.display = 'none';
  $('#qr-ph').style.display = 'flex';
  ['b30','songs','suggest','history','leaderboard'].forEach(t => {
    const el = $(`#${t}-content`); if (el) { el.innerHTML = ''; el.dataset.loaded = ''; }
  });
}

// ===== Tabs =====
function switchTab(name) {
  currentTab = name;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.toggle('active', c.dataset.tab === name));
  if (name === 'b30') loadB30();
  else if (name === 'songs') loadAllScores();
  else if (name === 'suggest') loadSuggest();
  else if (name === 'history') loadHistory();
  else if (name === 'leaderboard') loadLeaderboard();
}

// ===== 骨架屏 =====
function b30Skeleton(n=8) {
  let html = '<div class="b30-skeleton">';
  for (let i = 0; i < n; i++) {
    html += `<div class="skel-card">
      <div class="skel-ill skeleton" style="aspect-ratio:16/9"></div>
      <div class="skel-body"><div class="skel-line skeleton" style="width:60%"></div>
      <div class="skel-line skeleton" style="width:40%;height:10px"></div></div></div>`;
  }
  return html + '</div>';
}

function tableSkeleton(rows=8) {
  let html = '<div class="table-skeleton"><table class="tbl"><tbody>';
  for (let i = 0; i < rows; i++) {
    html += `<tr class="skel-row"><td><div class="skeleton" style="width:20px;height:14px"></div></td>
    <td><div class="skeleton" style="width:120px;height:14px"></div></td>
    <td><div class="skeleton" style="width:30px;height:14px"></div></td>
    <td><div class="skeleton" style="width:30px;height:14px"></div></td>
    <td><div class="skeleton" style="width:60px;height:14px"></div></td>
    <td><div class="skeleton" style="width:50px;height:14px"></div></td>
    <td><div class="skeleton" style="width:40px;height:14px"></div></td>
    <td><div class="skeleton" style="width:30px;height:14px"></div></td></tr>`;
  }
  return html + '</tbody></table></div>';
}

// ===== B30 =====
async function loadB30() {
  const el = $('#b30-content');
  el.innerHTML = b30Skeleton();
  try {
    let url = `/api/user/b30?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`;
    if (cachedUserId) url += `&user_id=${cachedUserId}`;
    const r = await fetch(url);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail||r.statusText}</div>`; return; }
    const d = await r.json();

    $('#p-name').textContent = d.player.nickname || cachedPlayerName || '未知';
    $('#p-id').textContent = d.player.player_id ? 'ID: ' + d.player.player_id : '';
    $('#s-rks').textContent = (d.save_rks||0).toFixed(2);
    $('#s-com-rks').textContent = (d.computed_rks||0).toFixed(2);
    $('#s-rank').textContent = d.challenge_rank || '--';
    $('#s-songs').textContent = d.total_songs || 0;
    $('#s-cleared').textContent = d.stats.cleared || 0;
    $('#s-fc').textContent = d.stats.fc || 0;
    $('#s-phi').textContent = d.stats.phi || 0;

    const b30 = d.b30 || [];
    if (!b30.length) { el.innerHTML = '<div class="note">没有成绩数据</div>'; return; }
    el.innerHTML = '<div class="b30-grid"></div>';
    const grid = el.querySelector('.b30-grid');
    b30.forEach((s, i) => {
      const rankCls = s.acc >= 100 ? 'phi' : '';
      grid.insertAdjacentHTML('beforeend', `
        <div class="score-card">
          <div class="ill-wrap">
            <img class="ill" loading="lazy" src="${s.illustration}" alt="${esc(s.song)}" onerror="this.style.display='none'">
            <div class="rank-badge ${rankCls}">#${i+1}</div>
          </div>
          <div class="body">
            <div class="song-name" title="${esc(s.song)}">${esc(s.song)}</div>
            <div class="meta">
              <span class="diff diff-${s.level}">${s.level} ${s.difficulty.toFixed(1)}</span>
              <span class="rt rt-${s.rating}">${s.rating}</span>
            </div>
            <div class="meta">
              <span class="acc">${s.acc.toFixed(2)}%</span>
              <span class="rks">${s.rks.toFixed(2)}</span>
            </div>
          </div>
        </div>`);
    });
  } catch(e) { el.innerHTML = `<div class="error">加载失败: ${e}</div>`; }
}

// ===== All Scores =====
async function loadAllScores() {
  const el = $('#songs-content');
  if (el.dataset.loaded === '1') return;
  el.innerHTML = tableSkeleton();
  try {
    const r = await fetch(`/api/user/all-scores?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail}</div>`; return; }
    const d = await r.json();
    const scores = d.scores || [];
    let html = `<div class="search-box"><input id="song-search" placeholder="🔍 搜索曲目名..." oninput="filterSongs()"></div>`;
    html += `<div class="note">共 ${scores.length} 条成绩</div>`;
    html += '<div class="table-wrap"><table class="tbl"><thead><tr><th>#</th><th>曲目</th><th>难度</th><th>定数</th><th>分数</th><th>ACC</th><th>RKS</th><th>评级</th></tr></thead><tbody id="songs-tbody">';
    scores.forEach((s, i) => {
      html += `<tr data-song="${esc(s.song.toLowerCase())}">
        <td>${i+1}</td><td>${esc(s.song)}</td>
        <td><span class="diff diff-${s.level}">${s.level}</span></td>
        <td>${s.difficulty.toFixed(1)}</td><td>${s.score.toLocaleString()}</td>
        <td style="font-family:monospace">${s.acc.toFixed(2)}%</td>
        <td style="font-family:monospace;color:var(--accent);font-weight:600">${s.rks.toFixed(2)}</td>
        <td><span class="rt rt-${s.rating}">${s.rating}</span></td></tr>`;
    });
    html += '</tbody></table></div>';
    el.innerHTML = html;
    el.dataset.loaded = '1';
  } catch(e) { el.innerHTML = `<div class="error">${e}</div>`; }
}

function filterSongs() {
  const q = ($('#song-search')?.value || '').toLowerCase();
  document.querySelectorAll('#songs-tbody tr').forEach(tr => {
    tr.style.display = tr.dataset.song.includes(q) ? '' : 'none';
  });
}

// ===== Suggest =====
async function loadSuggest() {
  const el = $('#suggest-content');
  el.innerHTML = '<div class="loading">⏳ 正在计算推分建议...</div>';
  try {
    const r = await fetch(`/api/user/suggest?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail}</div>`; return; }
    const d = await r.json();
    const sugs = d.suggestions || [];
    let html = `<div class="note">当前 RKS: <b>${d.save_rks}</b> → 目标: <b>${d.target_rks}</b> (需提升 ${d.min_up_rks})</div>`;
    if (!sugs.length) {
      html += '<div class="note">🎉 暂无可推分的曲目，你已经很强了！</div>';
    } else {
      html += '<div class="suggest-list">';
      sugs.forEach(s => {
        html += `
          <div class="suggest-card grade-${s.suggest_grade}">
            <img class="ill" loading="lazy" src="${s.illustration}" alt="${esc(s.song)}" onerror="this.style.display='none'">
            <div class="info">
              <div class="name" title="${esc(s.song)}">${esc(s.song)}</div>
              <div class="meta">
                <span class="diff diff-${s.level}">${s.level} ${s.difficulty.toFixed(1)}</span>
                当前 ${s.acc.toFixed(2)}% → RKS ${s.rks.toFixed(2)}
              </div>
            </div>
            <div class="acc-bar">
              <div class="acc-needed">${s.acc_needed.toFixed(2)}%</div>
              <div class="acc-diff">+${s.acc_diff.toFixed(2)}%</div>
            </div>
          </div>`;
      });
      html += '</div>';
    }
    el.innerHTML = html;
  } catch(e) { el.innerHTML = `<div class="error">${e}</div>`; }
}

// ===== History =====
async function loadHistory() {
  const el = $('#history-content');
  el.innerHTML = '<div class="loading">正在加载历史...</div>';
  try {
    let url = `/api/user/history?session_token=${encodeURIComponent(sessionToken)}`;
    if (cachedUserId) url += `&user_id=${cachedUserId}`;
    const r = await fetch(url);
    const d = await r.json();
    const trend = d.trend || [];
    if (!trend.length) {
      el.innerHTML = '<div class="note">暂无历史记录，每次查看 B30 会自动保存快照</div>';
      return;
    }
    let html = '<div class="history-chart"><h3 style="margin-bottom:12px">📈 RKS 变化趋势</h3>';
    html += renderTrendChart(trend);
    html += '</div>';
    html += '<div class="history-list">';
    trend.slice().reverse().forEach(h => {
      const dt = h.ts ? new Date(h.ts) : new Date();
      html += `<div class="history-item">
        <span style="color:var(--muted);font-size:12px">${dt.toLocaleString('zh-CN')}</span>
        <span style="font-family:monospace;font-weight:bold;color:var(--accent)">${(h.save_rks||0).toFixed(2)} / ${(h.computed_rks||0).toFixed(2)}</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { el.innerHTML = `<div class="error">${e}</div>`; }
}

function renderTrendChart(trend) {
  if (trend.length < 2) return '<div class="note">至少需要 2 条记录才能绘制趋势</div>';
  const w = 700, h = 180, pad = 40;
  const vals = trend.map(t => t.save_rks || 0);
  const min = Math.min(...vals) - 0.1;
  const max = Math.max(...vals) + 0.1;
  const range = max - min || 1;
  const step = (w - pad * 2) / Math.max(1, trend.length - 1);
  const pts = trend.map((t, i) => {
    const x = pad + i * step;
    const y = h - pad - ((t.save_rks || 0) - min) / range * (h - pad * 2);
    return `${x},${y}`;
  }).join(' ');
  const accent = getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() || '#6ea8fe';
  const muted = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim() || '#888';
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:700px">
    <polyline points="${pts}" fill="none" stroke="${accent}" stroke-width="2"/>
    ${trend.map((t, i) => {
      const x = pad + i * step;
      const y = h - pad - ((t.save_rks || 0) - min) / range * (h - pad * 2);
      return `<circle cx="${x}" cy="${y}" r="3" fill="${accent}"/><text x="${x}" y="${y-8}" fill="${muted}" font-size="10" text-anchor="middle">${(t.save_rks||0).toFixed(2)}</text>`;
    }).join('')}
  </svg>`;
}

// ===== Leaderboard =====
async function loadLeaderboard() {
  const el = $('#leaderboard-content');
  if (el.dataset.loaded === '1') return;
  el.innerHTML = '<div class="loading">正在加载排行榜...</div>';
  try {
    const r = await fetch('/api/leaderboard?limit=100');
    const d = await r.json();
    const lb = d.leaderboard || [];
    if (!lb.length) {
      el.innerHTML = '<div class="note">排行榜暂无数据（需要配置 Supabase 并有用户查看过 B30）</div>';
      return;
    }
    let html = '<div class="table-wrap"><table class="tbl"><thead><tr><th>#</th><th>玩家</th><th>RKS (存档)</th><th>RKS (计算)</th><th>更新时间</th></tr></thead><tbody>';
    lb.forEach((u, i) => {
      const dt = u.created_at ? new Date(u.created_at) : null;
      const dtStr = dt ? dt.toLocaleDateString('zh-CN') : '--';
      const isMe = (cachedUserId && u.user_id === cachedUserId);
      html += `<tr${isMe ? ' style="background:rgba(110,168,254,.1)"' : ''}>
        <td style="font-weight:bold;color:var(--accent)">${i+1}</td>
        <td>${esc(u.player_name || '匿名')} ${isMe ? '←' : ''}</td>
        <td style="font-family:monospace">${(u.save_rks||0).toFixed(2)}</td>
        <td style="font-family:monospace;color:var(--green)">${(u.computed_rks||0).toFixed(2)}</td>
        <td style="color:var(--muted);font-size:12px">${dtStr}</td>
      </tr>`;
    });
    html += '</tbody></table></div>';
    el.innerHTML = html;
    el.dataset.loaded = '1';
  } catch(e) { el.innerHTML = `<div class="error">${e}</div>`; }
}

// ===== Utils =====
const $ = s => document.querySelector(s);
function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
