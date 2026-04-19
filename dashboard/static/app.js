// Forge Prime Dashboard — vanilla JS, no framework

let currentProject = null;
const REFRESH_INTERVAL = 30000;

// ---------------------------------------------------------------------------
// View routing
// ---------------------------------------------------------------------------

function showView(name, projectName) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.getElementById('view-' + name).classList.add('active');
  if (name === 'overview') loadOverview();
  if (name === 'project' && projectName) loadProject(projectName);
  if (name === 'models') loadModels();
  if (name === 'wiki') loadWiki();
}

// ---------------------------------------------------------------------------
// Overview
// ---------------------------------------------------------------------------

async function loadOverview() {
  const container = document.getElementById('project-cards');
  container.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const projects = await fetch('/api/projects').then(r => r.json());
    if (!projects.length) {
      container.innerHTML = '<p class="loading">No projects registered. Run <code>forge init</code> in a project.</p>';
      return;
    }
    container.innerHTML = '';
    for (const p of projects) {
      const pct = p.chunks_total ? Math.round(p.chunks_done / p.chunks_total * 100) : 0;
      const gitBadge = p.git_clean
        ? '<span class="git-clean">● clean</span>'
        : '<span class="git-dirty">● dirty</span>';
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>${escHtml(p.name)} ${gitBadge}</h3>
        <div class="stat">${p.chunks_done}/${p.chunks_total}</div>
        <div class="meta">chunks done &nbsp;·&nbsp; ${pct}% complete</div>
      `;
      card.onclick = () => showView('project', p.name);
      container.appendChild(card);
    }
  } catch (e) {
    container.innerHTML = `<p class="loading">Error: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Project view
// ---------------------------------------------------------------------------

async function loadProject(name) {
  currentProject = name;
  document.getElementById('project-title').textContent = name;
  const tbody = document.getElementById('chunk-rows');
  tbody.innerHTML = '<tr><td colspan="7" class="loading">Loading…</td></tr>';
  try {
    const chunks = await fetch(`/api/chunks/${encodeURIComponent(name)}`).then(r => r.json());
    tbody.innerHTML = '';
    for (const c of chunks) {
      const statusClass = {
        DONE: 'badge-done', PENDING: 'badge-pending',
        IN_PROGRESS: 'badge-in-progress', FAILED: 'badge-failed'
      }[c.status] || 'badge-pending';
      const tr = document.createElement('tr');
      tr.innerHTML = `
        <td>${escHtml(c.id)}</td>
        <td>${escHtml(c.title || '')}</td>
        <td><span class="badge ${statusClass}">${c.status}</span></td>
        <td>${escHtml(c.model_used || c.model_alias || '—')}</td>
        <td>${fmt(c.input_tokens)}</td>
        <td>${fmt(c.output_tokens)}</td>
        <td>${c.estimated_cost_usd ? '$' + Number(c.estimated_cost_usd).toFixed(4) : '—'}</td>
      `;
      tbody.appendChild(tr);
    }
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7">Error: ${e.message}</td></tr>`;
  }
}

// ---------------------------------------------------------------------------
// Models view
// ---------------------------------------------------------------------------

async function loadModels() {
  const container = document.getElementById('model-cards');
  container.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const data = await fetch('/api/models').then(r => r.json());
    const models = Object.entries(data);
    if (!models.length) {
      container.innerHTML = '<p class="loading">No model usage recorded yet.</p>';
      return;
    }
    container.innerHTML = '';
    for (const [model, stats] of models) {
      const card = document.createElement('div');
      card.className = 'card';
      card.innerHTML = `
        <h3>${escHtml(model)}</h3>
        <div class="stat">${fmt(stats.input_tokens + stats.output_tokens)}</div>
        <div class="meta">
          tokens total &nbsp;·&nbsp;
          in: ${fmt(stats.input_tokens)} / out: ${fmt(stats.output_tokens)}<br>
          cost: $${Number(stats.cost_usd || 0).toFixed(4)}
        </div>
      `;
      container.appendChild(card);
    }
  } catch (e) {
    container.innerHTML = `<p class="loading">Error: ${e.message}</p>`;
  }
}

// ---------------------------------------------------------------------------
// Wiki view
// ---------------------------------------------------------------------------

async function loadWiki() {
  const list = document.getElementById('article-list');
  list.innerHTML = '<p class="loading">Loading…</p>';
  try {
    const articles = await fetch('/api/wiki/articles').then(r => r.json());
    list.innerHTML = '';
    for (const a of articles) {
      const div = document.createElement('div');
      div.className = 'article-item';
      div.innerHTML = `<div>${escHtml(a.title)}</div><div class="cat">${escHtml(a.category)}</div>`;
      div.onclick = () => loadArticle(a.category, a.filename);
      list.appendChild(div);
    }
    if (!articles.length) list.innerHTML = '<p class="loading">No wiki articles yet.</p>';
  } catch (e) {
    list.innerHTML = `<p class="loading">Error: ${e.message}</p>`;
  }
}

async function loadArticle(category, filename) {
  const content = document.getElementById('article-content');
  content.textContent = 'Loading…';
  try {
    const r = await fetch(`/api/wiki/article/${encodeURIComponent(category)}/${encodeURIComponent(filename)}`);
    if (!r.ok) throw new Error(r.statusText);
    content.textContent = await r.text();
  } catch (e) {
    content.textContent = `Error: ${e.message}`;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function fmt(n) {
  if (!n) return '0';
  return Number(n).toLocaleString();
}

function tickRefresh() {
  const el = document.getElementById('refresh-indicator');
  el.textContent = 'Refreshed ' + new Date().toLocaleTimeString();
}

// ---------------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------------

showView('overview');
setInterval(() => {
  if (document.querySelector('#view-overview.active')) loadOverview();
  if (document.querySelector('#view-project.active') && currentProject) loadProject(currentProject);
  if (document.querySelector('#view-models.active')) loadModels();
  tickRefresh();
}, REFRESH_INTERVAL);
