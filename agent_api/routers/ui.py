from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

HTML = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Comms</title>
<style>
  :root { --bg: #0d1117; --card: #161b22; --border: #30363d; --text: #e6edf3;
          --muted: #8b949e; --accent: #58a6ff; --green: #3fb950; --yellow: #d29922;
          --red: #f85149; --purple: #bc8cff; }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif;
         background: var(--bg); color: var(--text); line-height: 1.5; }
  .container { max-width: 960px; margin: 0 auto; padding: 24px 16px; }
  h1 { font-size: 20px; font-weight: 600; margin-bottom: 16px; }
  .tabs { display: flex; gap: 0; border-bottom: 1px solid var(--border); margin-bottom: 16px; }
  .tab { padding: 8px 16px; cursor: pointer; color: var(--muted); border-bottom: 2px solid transparent;
         font-size: 14px; font-weight: 500; background: none; border-top: none; border-left: none; border-right: none; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--text); border-bottom-color: var(--accent); }
  .filters { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; align-items: center; }
  .filters input, .filters select { background: var(--card); border: 1px solid var(--border); color: var(--text);
         padding: 6px 10px; border-radius: 6px; font-size: 13px; }
  .filters input::placeholder { color: var(--muted); }
  .filters select { cursor: pointer; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }
  .badge-pending { background: #30363d; color: var(--muted); }
  .badge-in_progress { background: #1a3a2a; color: var(--green); }
  .badge-blocked { background: #3d2a1a; color: var(--yellow); }
  .badge-done { background: #1a2a3d; color: var(--accent); }
  .badge-cancelled { background: #3d1a1a; color: var(--red); }
  .priority { font-weight: 700; font-size: 12px; }
  .p1 { color: var(--muted); } .p2 { color: var(--text); } .p3 { color: var(--yellow); }
  .p4 { color: #ff7b00; } .p5 { color: var(--red); }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
          padding: 12px 16px; margin-bottom: 8px; }
  .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 4px; }
  .card-meta { font-size: 12px; color: var(--muted); display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
  .card-content { font-size: 14px; white-space: pre-wrap; word-break: break-word; margin-top: 6px; }
  .card-title { font-size: 15px; font-weight: 600; }
  .username { color: var(--purple); font-weight: 600; font-size: 13px; }
  .project-tag { background: #1a2a3d; color: var(--accent); padding: 1px 6px; border-radius: 4px; font-size: 11px; }
  .pager { display: flex; gap: 8px; justify-content: center; margin-top: 16px; align-items: center; }
  .pager button { background: var(--card); border: 1px solid var(--border); color: var(--text);
         padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .pager button:disabled { opacity: 0.4; cursor: default; }
  .pager span { font-size: 13px; color: var(--muted); }
  .empty { text-align: center; color: var(--muted); padding: 40px; font-size: 14px; }
  .count { font-size: 13px; color: var(--muted); margin-bottom: 12px; }
  .auto-refresh { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin-left: auto; }
  .auto-refresh input { width: auto; }
</style>
</head>
<body>
<div class="container">
  <h1>Agent Comms</h1>
  <div class="tabs">
    <button class="tab active" data-tab="journal">Journal</button>
    <button class="tab" data-tab="tasks">Tasks</button>
  </div>

  <!-- Journal view -->
  <div id="journal-view">
    <div class="filters">
      <input id="j-user" placeholder="username" />
      <input id="j-project" placeholder="project" />
      <label class="auto-refresh"><input type="checkbox" id="j-auto" checked> auto-refresh</label>
    </div>
    <div class="count" id="j-count"></div>
    <div id="j-list"></div>
    <div class="pager">
      <button id="j-prev" disabled>&larr; Newer</button>
      <span id="j-page"></span>
      <button id="j-next">Older &rarr;</button>
    </div>
  </div>

  <!-- Tasks view -->
  <div id="tasks-view" style="display:none">
    <div class="filters">
      <input id="t-user" placeholder="username" />
      <input id="t-project" placeholder="project" />
      <select id="t-status">
        <option value="">all statuses</option>
        <option value="pending">pending</option>
        <option value="in_progress">in_progress</option>
        <option value="blocked">blocked</option>
        <option value="done">done</option>
        <option value="cancelled">cancelled</option>
      </select>
      <select id="t-priority">
        <option value="">all priorities</option>
        <option value="5">P5 (highest)</option>
        <option value="4">P4</option>
        <option value="3">P3</option>
        <option value="2">P2</option>
        <option value="1">P1 (lowest)</option>
      </select>
      <label class="auto-refresh"><input type="checkbox" id="t-auto" checked> auto-refresh</label>
    </div>
    <div class="count" id="t-count"></div>
    <div id="t-list"></div>
    <div class="pager">
      <button id="t-prev" disabled>&larr; Prev</button>
      <span id="t-page"></span>
      <button id="t-next">Next &rarr;</button>
    </div>
  </div>
</div>

<script>
const PER_PAGE = 30;
let jOffset = 0, tOffset = 0;
let jTotal = 0, tTotal = 0;
let refreshTimer = null;

function qs(params) {
  return Object.entries(params).filter(([,v]) => v).map(([k,v]) => `${k}=${encodeURIComponent(v)}`).join('&');
}

function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso + (iso.endsWith('Z') ? '' : 'Z')).getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

function renderJournalEntry(e) {
  return `<div class="card">
    <div class="card-header">
      <div class="card-meta">
        <span class="username">${esc(e.username)}</span>
        ${e.project ? `<span class="project-tag">${esc(e.project)}</span>` : ''}
      </div>
      <div class="card-meta"><span title="${esc(e.created_at)}">${timeAgo(e.created_at)}</span></div>
    </div>
    <div class="card-content">${esc(e.content)}</div>
  </div>`;
}

function renderTask(t) {
  return `<div class="card">
    <div class="card-header">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="priority p${t.priority}">P${t.priority}</span>
        <span class="badge badge-${t.status}">${t.status}</span>
        <span class="card-title">${esc(t.title)}</span>
      </div>
      <div class="card-meta"><span class="username">${esc(t.username)}</span></div>
    </div>
    <div class="card-meta" style="margin-top:4px">
      ${t.project ? `<span class="project-tag">${esc(t.project)}</span>` : ''}
      <span title="${esc(t.created_at)}">created ${timeAgo(t.created_at)}</span>
      <span title="${esc(t.updated_at)}">updated ${timeAgo(t.updated_at)}</span>
    </div>
    ${t.description ? `<div class="card-content">${esc(t.description)}</div>` : ''}
  </div>`;
}

function esc(s) {
  if (!s) return '';
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

async function loadJournal() {
  const p = qs({ username: g('j-user').value, project: g('j-project').value,
                 limit: PER_PAGE, offset: jOffset });
  const res = await fetch('/journal?' + p);
  const data = await res.json();
  jTotal = data.total;
  g('j-list').innerHTML = data.items.length
    ? data.items.map(renderJournalEntry).join('')
    : '<div class="empty">No journal entries</div>';
  updatePager('j', jOffset, jTotal);
}

async function loadTasks() {
  const p = qs({ username: g('t-user').value, project: g('t-project').value,
                 status: g('t-status').value, priority: g('t-priority').value,
                 limit: PER_PAGE, offset: tOffset });
  const res = await fetch('/tasks?' + p);
  const data = await res.json();
  tTotal = data.total;
  g('t-list').innerHTML = data.items.length
    ? data.items.map(renderTask).join('')
    : '<div class="empty">No tasks</div>';
  updatePager('t', tOffset, tTotal);
}

function updatePager(prefix, offset, total) {
  const page = Math.floor(offset / PER_PAGE) + 1;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  g(prefix + '-count').textContent = total + (total === 1 ? ' item' : ' items');
  g(prefix + '-page').textContent = `${page} / ${pages}`;
  g(prefix + '-prev').disabled = offset === 0;
  g(prefix + '-next').disabled = offset + PER_PAGE >= total;
}

function g(id) { return document.getElementById(id); }

// Tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const which = tab.dataset.tab;
    g('journal-view').style.display = which === 'journal' ? '' : 'none';
    g('tasks-view').style.display = which === 'tasks' ? '' : 'none';
    refresh();
  });
});

// Pagination
g('j-prev').onclick = () => { jOffset = Math.max(0, jOffset - PER_PAGE); loadJournal(); };
g('j-next').onclick = () => { jOffset += PER_PAGE; loadJournal(); };
g('t-prev').onclick = () => { tOffset = Math.max(0, tOffset - PER_PAGE); loadTasks(); };
g('t-next').onclick = () => { tOffset += PER_PAGE; loadTasks(); };

// Filter on change (debounced)
let filterTimeout;
['j-user','j-project'].forEach(id => g(id).addEventListener('input', () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(() => { jOffset = 0; loadJournal(); }, 300);
}));
['t-user','t-project'].forEach(id => g(id).addEventListener('input', () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(() => { tOffset = 0; loadTasks(); }, 300);
}));
['t-status','t-priority'].forEach(id => g(id).addEventListener('change', () => { tOffset = 0; loadTasks(); }));

function refresh() {
  const active = document.querySelector('.tab.active').dataset.tab;
  if (active === 'journal') loadJournal(); else loadTasks();
}

// Auto-refresh
function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    const active = document.querySelector('.tab.active').dataset.tab;
    if (active === 'journal' && g('j-auto').checked) loadJournal();
    if (active === 'tasks' && g('t-auto').checked) loadTasks();
  }, 5000);
}
startAutoRefresh();

// Initial load
loadJournal();
</script>
</body>
</html>
"""


@router.get("/ui", response_class=HTMLResponse)
def ui():
    return HTML
