// Phi-Plugin Web — 前端逻辑
let selectedGlobal = false;
let loginSessionId = null;
let pollTimer = null;
let sessionToken = null;
let isGlobal = false;
let allSongsCache = null;
let currentTab = 'b30';

// ===== Login =====
function selectServer(g) {
  selectedGlobal = g;
  $('#cn-btn').classList.toggle('active', !g);
  $('#gb-btn').classList.toggle('active', g);
}

async function startLogin() {
  $('#login-status').textContent = '正在获取二维码...';
  $('#login-btn').disabled = true;
  try {
    const r = await fetch('/api/login/qrcode?is_global=' + selectedGlobal, {method:'POST'});
    const d = await r.json();
    loginSessionId = d.session_id;
    $('#qr-img-el').src = 'https://api.qrserver.com/v1/create-qr-code/?size=180x180&data=' + encodeURIComponent(d.qr_url);
    $('#qr-img').style.display = 'block';
    $('#qr-ph').style.display = 'none';
    $('#login-status').textContent = '请使用 TapTap App 扫描二维码';
    $('#login-btn').textContent = '重新获取';
    $('#login-btn').disabled = false;
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollLogin, 2000);
  } catch(e) {
    $('#login-status').textContent = '获取失败: ' + e;
    $('#login-btn').disabled = false;
  }
}

async function pollLogin() {
  if (!loginSessionId) return;
  try {
    const r = await fetch('/api/login/check?session_id=' + loginSessionId);
    const d = await r.json();
    if (d.status === 'waiting') {
      $('#login-status').textContent = '等待扫码...';
    } else if (d.status === 'scanned') {
      $('#login-status').textContent = '已扫描，请在 TapTap 中确认';
    } else if (d.status === 'success') {
      clearInterval(pollTimer); pollTimer = null;
      sessionToken = d.session_token;
      isGlobal = d.is_global;
      $('#login-status').textContent = '登录成功！';
      setTimeout(() => {
        $('#login-page').style.display = 'none';
        $('#dashboard').style.display = 'block';
        switchTab('b30');
      }, 500);
    } else if (d.status === 'error') {
      clearInterval(pollTimer); pollTimer = null;
      $('#login-status').textContent = '失败: ' + (d.message||'');
      $('#login-btn').disabled = false;
    }
  } catch(e) {}
}

function logout() {
  sessionToken = null; isGlobal = false;
  $('#dashboard').style.display = 'none';
  $('#login-page').style.display = 'flex';
  $('#login-btn').disabled = false;
  $('#login-btn').textContent = '获取二维码';
  $('#login-status').textContent = '';
  $('#qr-img').style.display = 'none';
  $('#qr-ph').style.display = 'flex';
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
}

// ===== B30 =====
async function loadB30() {
  const el = $('#b30-content');
  el.innerHTML = '<div class="loading">正在获取存档，请稍候...</div>';
  try {
    const r = await fetch(`/api/user/b30?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail||r.statusText}</div>`; return; }
    const d = await r.json();
    // Header
    $('#p-name').textContent = d.player.nickname || '未知';
    $('#p-id').textContent = d.player.player_id ? 'ID: ' + d.player.player_id : '';
    $('#s-rks').textContent = (d.save_rks||0).toFixed(2);
    $('#s-com-rks').textContent = (d.computed_rks||0).toFixed(2);
    $('#s-rank').textContent = d.challenge_rank || '--';
    $('#s-songs').textContent = d.total_songs || 0;
    $('#s-cleared').textContent = d.stats.cleared || 0;
    $('#s-fc').textContent = d.stats.fc || 0;
    $('#s-phi').textContent = d.stats.phi || 0;
    // B30 Grid
    const b30 = d.b30 || [];
    if (!b30.length) { el.innerHTML = '<div class="loading">没有成绩数据</div>'; return; }
    el.innerHTML = '<div class="b30-grid"></div>';
    const grid = el.querySelector('.b30-grid');
    b30.forEach((s, i) => {
      const rankClass = s.acc >= 100 ? 'phi' : '';
      grid.insertAdjacentHTML('beforeend', `
        <div class="score-card">
          <img class="ill" loading="lazy" src="${s.illustration}" alt="${esc(s.song)}"
               onerror="this.style.display='none'">
          <div class="body">
            <div class="rank ${rankClass}">#${i+1}</div>
            <div class="song-name">${esc(s.song)}</div>
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
  // 只加载一次
  if (el.dataset.loaded === '1') return;
  el.innerHTML = '<div class="loading">正在获取全部成绩...</div>';
  try {
    const r = await fetch(`/api/user/all-scores?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail}</div>`; return; }
    const d = await r.json();
    const scores = d.scores || [];
    let html = `<div class="search-box"><input id="song-search" placeholder="搜索曲目名..." oninput="filterSongs()"></div>`;
    html += `<div class="note">共 ${scores.length} 条成绩</div>`;
    html += '<table class="tbl"><thead><tr><th>#</th><th>曲目</th><th>难度</th><th>定数</th><th>分数</th><th>ACC</th><th>RKS</th><th>评级</th></tr></thead><tbody id="songs-tbody">';
    scores.forEach((s, i) => {
      html += `<tr data-song="${esc(s.song.toLowerCase())}">
        <td>${i+1}</td>
        <td>${esc(s.song)}</td>
        <td><span class="diff diff-${s.level}">${s.level}</span></td>
        <td>${s.difficulty.toFixed(1)}</td>
        <td>${s.score.toLocaleString()}</td>
        <td style="font-family:monospace">${s.acc.toFixed(2)}%</td>
        <td style="font-family:monospace;color:var(--accent);font-weight:600">${s.rks.toFixed(2)}</td>
        <td><span class="rt rt-${s.rating}">${s.rating}</span></td>
      </tr>`;
    });
    html += '</tbody></table>';
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
  el.innerHTML = '<div class="loading">正在计算推分建议...</div>';
  try {
    const r = await fetch(`/api/user/suggest?session_token=${encodeURIComponent(sessionToken)}&is_global=${isGlobal}`);
    if (!r.ok) { const e = await r.json(); el.innerHTML = `<div class="error">${e.detail}</div>`; return; }
    const d = await r.json();
    const sugs = d.suggestions || [];
    let html = `<div class="note">当前 RKS: <b>${d.save_rks}</b> → 目标: <b>${d.target_rks}</b> (需提升 ${d.min_up_rks})</div>`;
    if (!sugs.length) {
      html += '<div class="note">暂无可推分的曲目，你已经很强了！</div>';
    } else {
      html += '<div class="suggest-list">';
      sugs.forEach(s => {
        const gradeCls = 'grade-' + s.suggest_grade;
        html += `
          <div class="suggest-card ${gradeCls}">
            <img class="ill" loading="lazy" src="${s.illustration}" alt="${esc(s.song)}" onerror="this.style.display='none'">
            <div class="info">
              <div class="name">${esc(s.song)}</div>
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
    const r = await fetch(`/api/user/history?session_token=${encodeURIComponent(sessionToken)}`);
    const d = await r.json();
    const trend = d.trend || [];
    if (!trend.length) {
      el.innerHTML = '<div class="note">暂无历史记录，每次查看 B30 会自动保存快照</div>';
      return;
    }
    // RKS 趋势图 (SVG)
    let html = '<div class="history-chart"><h3 style="margin-bottom:12px">RKS 变化趋势</h3>';
    html += renderTrendChart(trend);
    html += '</div>';
    // 列表
    html += '<div class="history-list">';
    trend.slice().reverse().forEach(h => {
      const dt = new Date(h.ts);
      html += `<div class="history-item">
        <span class="ts">${dt.toLocaleString('zh-CN')}</span>
        <span class="rks">${(h.save_rks||0).toFixed(2)} / ${(h.computed_rks||0).toFixed(2)}</span>
      </div>`;
    });
    html += '</div>';
    el.innerHTML = html;
  } catch(e) { el.innerHTML = `<div class="error">${e}</div>`; }
}

function renderTrendChart(trend) {
  if (trend.length < 2) return '<div class="note">至少需要 2 条记录才能绘制趋势</div>';
  const w = 700, h = 160, pad = 40;
  const rksVals = trend.map(t => t.save_rks || 0);
  const min = Math.min(...rksVals) - 0.1;
  const max = Math.max(...rksVals) + 0.1;
  const range = max - min || 1;
  const step = (w - pad * 2) / (trend.length - 1);
  const pts = trend.map((t, i) => {
    const x = pad + i * step;
    const y = h - pad - ((t.save_rks || 0) - min) / range * (h - pad * 2);
    return `${x},${y}`;
  }).join(' ');
  return `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" style="max-width:700px">
    <polyline points="${pts}" fill="none" stroke="#6ea8fe" stroke-width="2"/>
    ${trend.map((t, i) => {
      const x = pad + i * step;
      const y = h - pad - ((t.save_rks || 0) - min) / range * (h - pad * 2);
      return `<circle cx="${x}" cy="${y}" r="3" fill="#6ea8fe"/><text x="${x}" y="${y-8}" fill="#888" font-size="10" text-anchor="middle">${(t.save_rks||0).toFixed(2)}</text>`;
    }).join('')}
  </svg>`;
}

// ===== Utils =====
const $ = s => document.querySelector(s);
function esc(t) { const d = document.createElement('div'); d.textContent = t; return d.innerHTML; }
