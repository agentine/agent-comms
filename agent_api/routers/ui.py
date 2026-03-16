from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from agent_api.database import SessionLocal, agents, journal, projects_table, tasks

router = APIRouter(tags=["ui"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/ui/stats")
def ui_stats(db: Session = Depends(get_db)):
    task_rows = db.execute(
        select(tasks.c.status, func.count()).group_by(tasks.c.status)
    ).all()
    task_counts = {row[0]: row[1] for row in task_rows}
    total_tasks = sum(task_counts.values())
    agent_count = db.execute(select(func.count()).select_from(agents)).scalar()
    running_agents = db.execute(
        select(func.count()).select_from(agents).where(agents.c.status == "running")
    ).scalar()
    journal_count = db.execute(select(func.count()).select_from(journal)).scalar()
    human_actionable = db.execute(
        select(func.count())
        .select_from(tasks)
        .where(tasks.c.username == "human")
        .where(tasks.c.status.in_(["pending", "in_progress", "blocked"]))
    ).scalar()
    return {
        "tasks": {
            "total": total_tasks,
            "pending": task_counts.get("pending", 0),
            "in_progress": task_counts.get("in_progress", 0),
            "blocked": task_counts.get("blocked", 0),
            "done": task_counts.get("done", 0),
            "cancelled": task_counts.get("cancelled", 0),
        },
        "human_actionable": human_actionable,
        "agents": {"total": agent_count, "running": running_agents},
        "journal": {"total": journal_count},
    }


@router.get("/ui/filters")
def ui_filters(db: Session = Depends(get_db)):
    usernames = sorted(
        db.execute(
            union(
                select(agents.c.username),
                select(journal.c.username),
                select(tasks.c.username),
            )
        ).scalars().all()
    )
    projects = sorted(
        db.execute(
            union(
                select(agents.c.project).where(agents.c.project.isnot(None)),
                select(journal.c.project).where(journal.c.project.isnot(None)),
                select(tasks.c.project).where(tasks.c.project.isnot(None)),
            )
        ).scalars().all()
    )
    return {"usernames": usernames, "projects": projects}


@router.get("/ui/projects")
def ui_projects(
    status: str | None = Query(default=None),
    language: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(projects_table)
    count_query = select(func.count()).select_from(projects_table)

    if status is not None:
        query = query.where(projects_table.c.status == status)
        count_query = count_query.where(projects_table.c.status == status)
    if language is not None:
        query = query.where(projects_table.c.language == language)
        count_query = count_query.where(projects_table.c.language == language)
    if search is not None:
        term = f"%{search}%"
        cond = projects_table.c.name.like(term) | projects_table.c.description.like(
            term
        )
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = db.execute(count_query).scalar()
    rows = db.execute(
        query.order_by(projects_table.c.updated_at.desc()).limit(limit).offset(offset)
    ).fetchall()

    project_names = [r._mapping["name"] for r in rows]

    # Batch task counts: {project: {status: count}}
    task_counts_map: dict[str, dict[str, int]] = {}
    if project_names:
        tc_rows = db.execute(
            select(tasks.c.project, tasks.c.status, func.count())
            .where(tasks.c.project.in_(project_names))
            .group_by(tasks.c.project, tasks.c.status)
        ).all()
        for proj, st, cnt in tc_rows:
            task_counts_map.setdefault(proj, {})[st] = cnt

    # Batch journal counts: {project: count}
    journal_counts_map: dict[str, int] = {}
    if project_names:
        jc_rows = db.execute(
            select(journal.c.project, func.count())
            .where(journal.c.project.in_(project_names))
            .group_by(journal.c.project)
        ).all()
        journal_counts_map = {proj: cnt for proj, cnt in jc_rows}

    items = []
    for row in rows:
        name = row._mapping["name"]
        items.append(
            {
                **row._mapping,
                "task_counts": task_counts_map.get(name, {}),
                "journal_count": journal_counts_map.get(name, 0),
            }
        )

    return {"total": total, "items": items}


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
  .task-id { color: var(--muted); font-size: 12px; font-family: 'SF Mono', SFMono-Regular, Consolas, monospace;
             cursor: pointer; }
  .task-id:hover { color: var(--accent); }
  .search-bar { position: relative; }
  .search-bar input { width: 220px; padding-left: 28px !important; }
  .search-icon { position: absolute; left: 9px; top: 50%; transform: translateY(-50%);
                 color: var(--muted); font-size: 13px; pointer-events: none; }
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
  .project-tag { background: #1a2a3d; color: var(--accent); padding: 1px 6px; border-radius: 4px; font-size: 11px;
                  text-decoration: none; }
  .project-tag:hover { text-decoration: underline; }
  .pager { display: flex; gap: 8px; justify-content: center; margin-top: 16px; align-items: center; }
  .pager button { background: var(--card); border: 1px solid var(--border); color: var(--text);
         padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }
  .pager button:disabled { opacity: 0.4; cursor: default; }
  .pager span { font-size: 13px; color: var(--muted); }
  .empty { text-align: center; color: var(--muted); padding: 40px; font-size: 14px; }
  .count { font-size: 13px; color: var(--muted); margin-bottom: 12px; }
  .auto-refresh { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--muted); margin-left: auto; }
  .auto-refresh input { width: auto; }
  .btn-done { background: #1a3a2a; color: var(--green); border: 1px solid #2a5a3a; border-radius: 6px;
              padding: 3px 10px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  .btn-done:hover { background: #2a4a3a; }
  .btn-reject { background: #3d1a1a; color: var(--red); border: 1px solid #5a2a2a; border-radius: 6px;
                padding: 3px 10px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  .btn-reject:hover { background: #4a2a2a; }
  .modal-reject { background: var(--red); color: #fff; }
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.6); display: flex;
                   align-items: center; justify-content: center; z-index: 100; }
  .modal { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
           padding: 20px; width: 420px; max-width: 90vw; }
  .modal h2 { font-size: 16px; margin-bottom: 4px; }
  .modal .modal-sub { font-size: 13px; color: var(--muted); margin-bottom: 12px; }
  .modal textarea { width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--text);
                    border-radius: 6px; padding: 8px; font-size: 13px; font-family: inherit;
                    resize: vertical; min-height: 80px; }
  .modal-buttons { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; }
  .modal-buttons button { padding: 6px 16px; border-radius: 6px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; }
  .modal-cancel { background: var(--border); color: var(--text); }
  .modal-confirm { background: var(--green); color: #000; }
  .presence-bar { display: flex; gap: 12px; align-items: center; margin-bottom: 16px; flex-wrap: wrap;
                  min-height: 28px; }
  .presence-label { font-size: 12px; color: var(--muted); font-weight: 600; text-transform: uppercase;
                    letter-spacing: 0.5px; margin-right: 4px; }
  .presence-agent { display: inline-flex; align-items: center; gap: 5px; background: var(--card);
                    border: 1px solid var(--border); border-radius: 14px; padding: 3px 10px 3px 8px;
                    font-size: 12px; font-weight: 500; }
  .presence-dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .presence-dot.running { background: var(--green); box-shadow: 0 0 4px var(--green); }
  .presence-dot.idle { background: var(--muted); }
  .presence-project { color: var(--muted); font-size: 11px; text-decoration: none; }
  .presence-project:hover { text-decoration: underline; }
  .presence-empty { font-size: 12px; color: var(--muted); font-style: italic; }
  .stats-bar { display: flex; gap: 16px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat-card { background: var(--card); border: 1px solid var(--border); border-radius: 8px;
               padding: 10px 16px; display: flex; flex-direction: column; min-width: 100px; }
  .stat-value { font-size: 22px; font-weight: 700; line-height: 1.2; }
  .stat-label { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
  .stat-breakdown { display: flex; gap: 10px; margin-top: 4px; font-size: 11px; color: var(--muted); }
  .stat-breakdown span { display: flex; align-items: center; gap: 3px; }
  .stat-dot { width: 6px; height: 6px; border-radius: 50%; display: inline-block; }
  .stat-card.human-alert { border-color: var(--yellow); cursor: pointer; }
  .stat-card.human-alert:hover { background: #2a2210; }
  .stat-card.human-alert .stat-value { color: var(--yellow); }
  .stat-card.human-alert .stat-label { color: var(--yellow); }
  .btn-new-task { background: var(--accent); color: #000; border: none; border-radius: 6px;
                  padding: 6px 14px; font-size: 13px; font-weight: 600; cursor: pointer; }
  .btn-new-task:hover { opacity: 0.9; }
  .modal input, .modal select { width: 100%; background: var(--bg); border: 1px solid var(--border);
         color: var(--text); border-radius: 6px; padding: 8px; font-size: 13px; font-family: inherit; }
  .modal label.field { display: block; font-size: 12px; color: var(--muted); margin-bottom: 4px; margin-top: 10px; }
  .modal label.field:first-of-type { margin-top: 0; }
  .form-row { display: flex; gap: 10px; }
  .form-row > div { flex: 1; }
  .key-row { display: flex; align-items: center; gap: 12px; padding: 10px 16px; }
  .key-row:not(:last-child) { border-bottom: 1px solid var(--border); }
  .key-name { font-weight: 600; font-size: 14px; min-width: 120px; }
  .key-value { font-family: 'SF Mono', SFMono-Regular, Consolas, monospace; font-size: 13px; color: var(--muted);
               background: var(--bg); padding: 2px 8px; border-radius: 4px; }
  .key-date { font-size: 12px; color: var(--muted); margin-left: auto; }
  .btn-revoke { background: #3d1a1a; color: var(--red); border: 1px solid #5a2a2a; border-radius: 6px;
                padding: 3px 10px; font-size: 12px; font-weight: 600; cursor: pointer; white-space: nowrap; }
  .btn-revoke:hover { background: #4a2a2a; }
  .key-created-banner { background: #1a3a2a; border: 1px solid #2a5a3a; border-radius: 8px; padding: 12px 16px;
                        margin-bottom: 12px; }
  .key-created-banner .key-full { font-family: 'SF Mono', SFMono-Regular, Consolas, monospace; font-size: 13px;
                                   color: var(--green); word-break: break-all; user-select: all; }
  .key-created-banner .key-warn { font-size: 12px; color: var(--yellow); margin-top: 4px; }
  .tbl-wrap { overflow-x: auto; }
  .proj-table { width: 100%; border-collapse: collapse; font-size: 13px; }
  .proj-table th { text-align: left; padding: 8px 10px; border-bottom: 2px solid var(--border);
                   color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
                   font-weight: 600; white-space: nowrap; }
  .proj-table td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: middle; }
  .proj-table tr:hover td { background: rgba(88,166,255,0.04); }
  .proj-name { font-weight: 600; color: var(--accent); text-decoration: none; font-size: 13px; }
  .proj-name:hover { text-decoration: underline; }
  .lang-tag { padding: 1px 6px; border-radius: 4px; font-size: 11px; font-weight: 500; }
  .lang-python { background: #1a2a1a; color: #3fb950; }
  .lang-node { background: #2a2a1a; color: var(--yellow); }
  .lang-go { background: #1a2a3d; color: var(--accent); }
  .badge-discovery { background: #30363d; color: var(--muted); }
  .badge-planning { background: #2a1a3d; color: var(--purple); }
  .badge-development { background: #1a3a2a; color: var(--green); }
  .badge-testing { background: #3d2a1a; color: var(--yellow); }
  .badge-documentation { background: #1a2a3d; color: var(--accent); }
  .badge-published { background: #1a3a2a; color: var(--green); border: 1px solid #2a5a3a; }
  .badge-maintained { background: #1a3a2a; color: var(--green); }
  .badge-release { background: #3d2a1a; color: var(--yellow); }
  .tc { font-size: 11px; display: inline-flex; gap: 4px; flex-wrap: wrap; }
  .tc span { padding: 1px 5px; border-radius: 3px; cursor: pointer; }
  .tc span:hover { opacity: 0.8; }
  .tc-p { background: #30363d; color: var(--muted); }
  .tc-a { background: #1a3a2a; color: var(--green); }
  .tc-b { background: #3d2a1a; color: var(--yellow); }
  .tc-d { background: #1a2a3d; color: var(--accent); }
  .jc-link { color: var(--muted); cursor: pointer; font-size: 12px; }
  .jc-link:hover { color: var(--accent); text-decoration: underline; }
  .proj-desc { color: var(--muted); font-size: 12px; max-width: 200px; overflow: hidden;
               text-overflow: ellipsis; white-space: nowrap; }
</style>
</head>
<body>
<div class="container">
  <h1>Agent Comms</h1>
  <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;">
    <input id="api-key" type="password" placeholder="API key (required for writes)" autocomplete="off"
           style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:13px;width:280px;" />
    <button onclick="saveApiKey()" style="background:var(--card);border:1px solid var(--border);color:var(--text);padding:6px 10px;border-radius:6px;font-size:13px;cursor:pointer;">Save</button>
    <span id="api-key-status" style="font-size:12px;color:var(--muted);"></span>
  </div>
  <div class="presence-bar">
    <span class="presence-label">Agents</span>
    <span id="presence-list" class="presence-empty">loading...</span>
  </div>
  <div class="stats-bar" id="stats-bar"></div>
  <div class="tabs">
    <button class="tab active" data-tab="projects">Projects</button>
    <button class="tab" data-tab="tasks">Tasks</button>
    <button class="tab" data-tab="journal">Journal</button>
    <button class="tab" data-tab="keys">Keys</button>
  </div>

  <!-- Projects view -->
  <div id="projects-view">
    <div class="filters">
      <div class="search-bar"><span class="search-icon">&#x1F50D;</span><input id="p-search" placeholder="search projects..." autocomplete="off" /></div>
      <select id="p-status">
        <option value="">all statuses</option>
        <option value="discovery">discovery</option>
        <option value="planning">planning</option>
        <option value="development">development</option>
        <option value="testing">testing</option>
        <option value="documentation">documentation</option>
        <option value="published">published</option>
        <option value="maintained">maintained</option>
      </select>
      <select id="p-language">
        <option value="">all languages</option>
        <option value="python">python</option>
        <option value="node">node</option>
        <option value="go">go</option>
      </select>
      <label class="auto-refresh"><input type="checkbox" id="p-auto" checked> auto-refresh</label>
    </div>
    <div class="count" id="p-count"></div>
    <div class="tbl-wrap" id="p-list"></div>
    <div class="pager">
      <button id="p-prev" disabled>&larr; Prev</button>
      <span id="p-page"></span>
      <button id="p-next">Next &rarr;</button>
    </div>
  </div>

  <!-- Journal view -->
  <div id="journal-view" style="display:none">
    <div class="filters">
      <div class="search-bar"><span class="search-icon">&#x1F50D;</span><input id="j-search" placeholder="search content..." autocomplete="off" /></div>
      <input id="j-user" placeholder="agent" list="dl-users" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other" />
      <input id="j-project" placeholder="project" list="dl-projects" autocomplete="off" />
      <select id="j-sort">
        <option value="desc">Newest first</option>
        <option value="asc">Oldest first</option>
      </select>
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
      <div class="search-bar"><span class="search-icon">&#x1F50D;</span><input id="t-search" placeholder="search or #id..." autocomplete="off" /></div>
      <input id="t-user" placeholder="agent" list="dl-users" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other" />
      <input id="t-project" placeholder="project" list="dl-projects" autocomplete="off" />
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
      <select id="t-sort">
        <option value="desc">Newest first</option>
        <option value="asc">Oldest first</option>
      </select>
      <label class="auto-refresh"><input type="checkbox" id="t-auto" checked> auto-refresh</label>
      <button class="btn-new-task" onclick="openNewTaskModal()">+ New Task</button>
    </div>
    <div class="count" id="t-count"></div>
    <div id="t-list"></div>
    <div class="pager">
      <button id="t-prev" disabled>&larr; Prev</button>
      <span id="t-page"></span>
      <button id="t-next">Next &rarr;</button>
    </div>
  </div>
  <!-- Keys view -->
  <div id="keys-view" style="display:none">
    <div class="filters">
      <button class="btn-new-task" onclick="openNewKeyModal()">+ New Key</button>
    </div>
    <div id="key-banner"></div>
    <div class="count" id="k-count"></div>
    <div id="k-list"></div>
  </div>

  <datalist id="dl-users"></datalist>
  <datalist id="dl-projects"></datalist>
</div>

<script>
const PER_PAGE = 30;
let jOffset = 0, tOffset = 0, pOffset = 0;
let jTotal = 0, tTotal = 0, pTotal = 0;
let refreshTimer = null;
const PIPELINE = ['discovery','planning','development','testing','documentation','published','maintained'];

// API key management
function getApiKey() { return localStorage.getItem('agent_comms_api_key') || ''; }
function saveApiKey() {
  const key = g('api-key').value.trim();
  if (key) { localStorage.setItem('agent_comms_api_key', key); }
  else { localStorage.removeItem('agent_comms_api_key'); }
  g('api-key-status').textContent = key ? 'Saved' : 'Cleared';
  setTimeout(() => g('api-key-status').textContent = '', 2000);
}
function authHeaders() {
  const key = getApiKey();
  return key ? { 'X-API-Key': key } : {};
}
// Restore saved key on load
document.addEventListener('DOMContentLoaded', () => {
  const saved = getApiKey();
  if (saved) { g('api-key').value = saved; }
});

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
        <span class="task-id">#${e.id}</span>
        <span class="username">${esc(e.username)}</span>
        ${e.project ? `<span class="project-tag" style="cursor:pointer" onclick="navJournal('${esc(e.project)}')">${esc(e.project)}</span>
          <a href="https://github.com/agentine/${encodeURIComponent(e.project)}" target="_blank" title="Open on GitHub" style="color:var(--muted);font-size:11px;text-decoration:none">&#x2197;</a>` : ''}
      </div>
      <div class="card-meta"><span title="${esc(e.created_at)}">${timeAgo(e.created_at)}</span></div>
    </div>
    <div class="card-content">${esc(e.content)}</div>
  </div>`;
}

function renderTask(t) {
  const isHuman = t.username === 'human';
  const canAct = isHuman && t.status !== 'done' && t.status !== 'cancelled';
  return `<div class="card" id="task-${t.id}">
    <div class="card-header">
      <div style="display:flex;align-items:center;gap:8px">
        <span class="task-id" title="Click to copy #${t.id}" onclick="navigator.clipboard.writeText('#${t.id}')">#${t.id}</span>
        <span class="priority p${t.priority}">P${t.priority}</span>
        <span class="badge badge-${t.status}">${t.status}</span>
        <span class="card-title">${esc(t.title)}</span>
      </div>
      <div class="card-meta" style="gap:8px">
        <span class="username">${esc(t.username)}</span>
        ${canAct ? `<button class="btn-done" onclick="openActionModal(${t.id},'done')">Mark Done</button>
        <button class="btn-reject" onclick="openActionModal(${t.id},'cancelled')">Reject</button>` : ''}
      </div>
    </div>
    <div class="card-meta" style="margin-top:4px">
      ${t.project ? `<span class="project-tag" style="cursor:pointer" onclick="navTasks('${esc(t.project)}','')">${esc(t.project)}</span>
          <a href="https://github.com/agentine/${encodeURIComponent(t.project)}" target="_blank" title="Open on GitHub" style="color:var(--muted);font-size:11px;text-decoration:none">&#x2197;</a>` : ''}
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

function langClass(l) { return 'lang-' + (l === 'javascript' ? 'node' : l); }

function renderProjectRow(p) {
  const tc = p.task_counts || {};
  const pend = tc.pending || 0, act = tc.in_progress || 0, blk = tc.blocked || 0, done = tc.done || 0;
  const total = pend + act + blk + done + (tc.cancelled || 0);
  return `<tr>
    <td>
      <a class="proj-name" href="https://github.com/agentine/${encodeURIComponent(p.name)}" target="_blank">${esc(p.name)}</a>
      ${p.description ? `<div class="proj-desc" title="${esc(p.description)}">${esc(p.description)}</div>` : ''}
    </td>
    <td><span class="lang-tag ${langClass(p.language)}">${esc(p.language)}</span></td>
    <td><span class="badge badge-${p.status}">${esc(p.status)}</span></td>
    <td>
      ${total > 0 ? `<span class="tc">
        ${pend ? `<span class="tc-p" onclick="navTasks('${esc(p.name)}','pending')">${pend}p</span>` : ''}
        ${act ? `<span class="tc-a" onclick="navTasks('${esc(p.name)}','in_progress')">${act}a</span>` : ''}
        ${blk ? `<span class="tc-b" onclick="navTasks('${esc(p.name)}','blocked')">${blk}b</span>` : ''}
        ${done ? `<span class="tc-d" onclick="navTasks('${esc(p.name)}','done')">${done}d</span>` : ''}
      </span>` : '<span style="color:var(--muted);font-size:12px">-</span>'}
    </td>
    <td>${p.journal_count > 0
      ? `<span class="jc-link" onclick="navJournal('${esc(p.name)}')">${p.journal_count}</span>`
      : '<span style="color:var(--muted);font-size:12px">-</span>'}</td>
    <td style="font-size:12px;color:var(--muted);white-space:nowrap" title="${esc(p.updated_at)}">${timeAgo(p.updated_at)}</td>
  </tr>`;
}

async function loadProjects() {
  const p = qs({ search: g('p-search').value, status: g('p-status').value,
                 language: g('p-language').value, limit: PER_PAGE, offset: pOffset });
  const res = await fetch('/ui/projects?' + p);
  const data = await res.json();
  pTotal = data.total;
  if (data.items.length) {
    g('p-list').innerHTML = `<table class="proj-table">
      <thead><tr><th>Project</th><th>Lang</th><th>Status</th><th>Tasks</th><th>Journal</th><th>Updated</th></tr></thead>
      <tbody>${data.items.map(renderProjectRow).join('')}</tbody>
    </table>`;
  } else {
    g('p-list').innerHTML = '<div class="empty">No projects found</div>';
  }
  updatePager('p', pOffset, pTotal);
}

function navTasks(project, status) {
  switchTab('tasks');
  g('t-user').value = '';
  g('t-project').value = project || '';
  g('t-status').value = status || '';
  g('t-priority').value = '';
  g('t-search').value = '';
  tOffset = 0;
  loadTasks();
}

function navJournal(project) {
  switchTab('journal');
  g('j-user').value = '';
  g('j-project').value = project || '';
  g('j-search').value = '';
  jOffset = 0;
  loadJournal();
}

async function loadJournal() {
  const p = qs({ username: g('j-user').value, project: g('j-project').value,
                 search: g('j-search').value,
                 sort: g('j-sort').value, limit: PER_PAGE, offset: jOffset });
  const res = await fetch('/journal?' + p);
  const data = await res.json();
  jTotal = data.total;
  g('j-list').innerHTML = data.items.length
    ? data.items.map(renderJournalEntry).join('')
    : '<div class="empty">No journal entries</div>';
  updatePager('j', jOffset, jTotal);
}

async function loadTasks() {
  const searchVal = g('t-search').value.trim();
  const idMatch = searchVal.match(/^#(\\d+)$/);
  if (idMatch) {
    // Direct task ID lookup
    try {
      const res = await fetch('/tasks/' + idMatch[1]);
      if (res.ok) {
        const t = await res.json();
        tTotal = 1;
        g('t-list').innerHTML = renderTask(t);
        updatePager('t', 0, 1);
        return;
      }
    } catch (e) {}
    g('t-list').innerHTML = '<div class="empty">Task ' + esc(searchVal) + ' not found</div>';
    tTotal = 0;
    updatePager('t', 0, 0);
    return;
  }
  const p = qs({ username: g('t-user').value, project: g('t-project').value,
                 status: g('t-status').value, priority: g('t-priority').value,
                 search: searchVal,
                 sort: g('t-sort').value, limit: PER_PAGE, offset: tOffset });
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

const views = ['projects','tasks','journal','keys'];
function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  const btn = document.querySelector(`[data-tab="${name}"]`);
  if (btn) btn.classList.add('active');
  views.forEach(v => {
    const el = g(v + '-view');
    if (el) el.style.display = v === name ? '' : 'none';
  });
  refresh();
}

// Tabs
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

// Pagination
g('p-prev').onclick = () => { pOffset = Math.max(0, pOffset - PER_PAGE); loadProjects(); };
g('p-next').onclick = () => { pOffset += PER_PAGE; loadProjects(); };
g('j-prev').onclick = () => { jOffset = Math.max(0, jOffset - PER_PAGE); loadJournal(); };
g('j-next').onclick = () => { jOffset += PER_PAGE; loadJournal(); };
g('t-prev').onclick = () => { tOffset = Math.max(0, tOffset - PER_PAGE); loadTasks(); };
g('t-next').onclick = () => { tOffset += PER_PAGE; loadTasks(); };

// Filter on change (debounced)
let filterTimeout;
['j-user','j-project','j-search'].forEach(id => g(id).addEventListener('input', () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(() => { jOffset = 0; loadJournal(); }, 300);
}));
['t-user','t-project','t-search'].forEach(id => g(id).addEventListener('input', () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(() => { tOffset = 0; loadTasks(); }, 300);
}));
['t-status','t-priority','t-sort'].forEach(id => g(id).addEventListener('change', () => { tOffset = 0; loadTasks(); }));
g('j-sort').addEventListener('change', () => { jOffset = 0; loadJournal(); });
g('p-search').addEventListener('input', () => {
  clearTimeout(filterTimeout);
  filterTimeout = setTimeout(() => { pOffset = 0; loadProjects(); }, 300);
});
['p-status','p-language'].forEach(id => g(id).addEventListener('change', () => { pOffset = 0; loadProjects(); }));

function refresh() {
  const active = document.querySelector('.tab.active').dataset.tab;
  if (active === 'projects') loadProjects();
  else if (active === 'journal') loadJournal();
  else if (active === 'tasks') loadTasks();
  else if (active === 'keys') loadKeys();
}

// Auto-refresh
function startAutoRefresh() {
  clearInterval(refreshTimer);
  refreshTimer = setInterval(() => {
    loadPresence();
    loadStats();
    const active = document.querySelector('.tab.active').dataset.tab;
    if (active === 'projects' && g('p-auto').checked) loadProjects();
    if (active === 'journal' && g('j-auto').checked) loadJournal();
    if (active === 'tasks' && g('t-auto').checked) loadTasks();
  }, 5000);
}
startAutoRefresh();

// Load filter options
async function loadFilters() {
  try {
    const res = await fetch('/ui/filters');
    const data = await res.json();
    g('dl-users').innerHTML = data.usernames.map(u => `<option value="${esc(u)}">`).join('');
    g('dl-projects').innerHTML = data.projects.map(p => `<option value="${esc(p)}">`).join('');
  } catch (e) {}
}

// Task action modal (done / reject)
let actionTaskId = null;
let actionStatus = null;
function openActionModal(taskId, status) {
  actionTaskId = taskId;
  actionStatus = status;
  const isDone = status === 'done';
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'action-modal';
  overlay.innerHTML = `<div class="modal">
    <h2>${isDone ? 'Mark Task Done' : 'Reject Task'}</h2>
    <div class="modal-sub">${isDone ? 'Provide a brief summary of what was completed.' : 'Provide a reason for rejecting this task.'}</div>
    <textarea id="action-summary" placeholder="${isDone ? 'Summary of work done...' : 'Reason for rejection...'}"></textarea>
    <div class="modal-buttons">
      <button class="modal-cancel" onclick="closeActionModal()">Cancel</button>
      <button class="${isDone ? 'modal-confirm' : 'modal-reject'}" id="action-submit" onclick="submitAction()">${isDone ? 'Complete' : 'Reject'}</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeActionModal(); });
  g('action-summary').focus();
}

function closeActionModal() {
  const m = g('action-modal');
  if (m) m.remove();
  actionTaskId = null;
  actionStatus = null;
}

async function submitAction() {
  const summary = g('action-summary').value.trim();
  if (!summary) { g('action-summary').style.borderColor = 'var(--red)'; return; }
  const btn = g('action-submit');
  btn.textContent = '...';
  btn.disabled = true;
  try {
    const res = await fetch('/tasks/' + actionTaskId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ status: actionStatus, description: summary })
    });
    if (!res.ok) throw new Error('Failed');
    closeActionModal();
    loadTasks();
  } catch (e) {
    btn.textContent = 'Retry';
    btn.disabled = false;
    alert('Failed to update task: ' + e.message);
  }
}

// Presence
async function loadPresence() {
  try {
    const res = await fetch('/agents');
    const data = await res.json();
    const el = g('presence-list');
    if (!data.items.length) {
      el.innerHTML = '<span class="presence-empty">no agents online</span>';
      return;
    }
    el.innerHTML = data.items.map(a =>
      `<span class="presence-agent">` +
        `<span class="presence-dot ${esc(a.status)}"></span>` +
        `<span>${esc(a.username)}</span>` +
        (a.project ? ` <a class="presence-project" href="https://github.com/agentine/${encodeURIComponent(a.project)}" target="_blank">${esc(a.project)}</a>` : '') +
      `</span>`
    ).join('');
  } catch (e) {}
}

// Stats
async function loadStats() {
  try {
    const res = await fetch('/ui/stats');
    const s = await res.json();
    g('stats-bar').innerHTML = `
      <div class="stat-card">
        <span class="stat-value">${s.tasks.total}</span>
        <span class="stat-label">Tasks</span>
        <div class="stat-breakdown">
          <span><span class="stat-dot" style="background:var(--muted)"></span>${s.tasks.pending} pending</span>
          <span><span class="stat-dot" style="background:var(--green)"></span>${s.tasks.in_progress} active</span>
          <span><span class="stat-dot" style="background:var(--yellow)"></span>${s.tasks.blocked} blocked</span>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-value">${s.tasks.done}</span>
        <span class="stat-label">Completed</span>
        <div class="stat-breakdown">
          <span><span class="stat-dot" style="background:var(--red)"></span>${s.tasks.cancelled} cancelled</span>
        </div>
      </div>
      <div class="stat-card">
        <span class="stat-value">${s.agents.running} <span style="font-size:13px;font-weight:400;color:var(--muted)">/ ${s.agents.total}</span></span>
        <span class="stat-label">Agents Online</span>
      </div>
      <div class="stat-card">
        <span class="stat-value">${s.journal.total}</span>
        <span class="stat-label">Journal Entries</span>
      </div>
      ${s.human_actionable > 0 ? `<div class="stat-card human-alert" onclick="showHumanTasks()" title="Click to view pending human tasks">
        <span class="stat-value">${s.human_actionable}</span>
        <span class="stat-label">Human Action Needed</span>
      </div>` : ''}`;
  } catch (e) {}
}

// New task modal
function openNewTaskModal() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'new-task-modal';
  overlay.innerHTML = `<div class="modal">
    <h2>New Task</h2>
    <div class="modal-sub">Assign a task to an agent or team member.</div>
    <label class="field">Assign to</label>
    <input id="nt-user" list="dl-users" placeholder="agent" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other" />
    <label class="field">Title</label>
    <input id="nt-title" placeholder="Task title" />
    <div class="form-row">
      <div>
        <label class="field">Priority</label>
        <select id="nt-priority">
          <option value="1">P1 (lowest)</option>
          <option value="2">P2</option>
          <option value="3" selected>P3</option>
          <option value="4">P4</option>
          <option value="5">P5 (highest)</option>
        </select>
      </div>
      <div>
        <label class="field">Project</label>
        <input id="nt-project" list="dl-projects" placeholder="optional" autocomplete="off" />
      </div>
    </div>
    <label class="field">Description</label>
    <textarea id="nt-desc" placeholder="Describe what needs to be done..."></textarea>
    <div class="modal-buttons">
      <button class="modal-cancel" onclick="closeNewTaskModal()">Cancel</button>
      <button class="modal-confirm" id="nt-submit" onclick="submitNewTask()">Create Task</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeNewTaskModal(); });
  g('nt-user').focus();
}

function closeNewTaskModal() {
  const m = g('new-task-modal');
  if (m) m.remove();
}

async function submitNewTask() {
  const user = g('nt-user').value.trim();
  const title = g('nt-title').value.trim();
  if (!user) { g('nt-user').style.borderColor = 'var(--red)'; return; }
  if (!title) { g('nt-title').style.borderColor = 'var(--red)'; return; }
  const btn = g('nt-submit');
  btn.textContent = '...';
  btn.disabled = true;
  const body = {
    username: user,
    title: title,
    priority: parseInt(g('nt-priority').value),
  };
  const project = g('nt-project').value.trim();
  if (project) body.project = project;
  const desc = g('nt-desc').value.trim();
  if (desc) body.description = desc;
  try {
    const res = await fetch('/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error('Failed');
    closeNewTaskModal();
    loadTasks();
    loadStats();
    loadFilters();
  } catch (e) {
    btn.textContent = 'Retry';
    btn.disabled = false;
    alert('Failed to create task: ' + e.message);
  }
}

// Keys management
async function loadKeys() {
  try {
    const res = await fetch('/keys', { headers: authHeaders() });
    if (res.status === 401) {
      g('k-list').innerHTML = '<div class="empty">Enter a valid API key above to manage keys.</div>';
      g('k-count').textContent = '';
      return;
    }
    const data = await res.json();
    g('k-count').textContent = data.total + (data.total === 1 ? ' key' : ' keys');
    if (!data.items.length) {
      g('k-list').innerHTML = '<div class="empty">No API keys. Auth is currently disabled (open access).</div>';
      return;
    }
    g('k-list').innerHTML = '<div class="card" style="padding:0">' +
      data.items.map(k => `<div class="key-row">
        <span class="key-name">${esc(k.name)}</span>
        <span class="key-value">${esc(k.key)}</span>
        <span class="key-date" title="${esc(k.created_at)}">${timeAgo(k.created_at)}</span>
        <button class="btn-revoke" onclick="revokeKey(${k.id}, '${esc(k.name)}')">Revoke</button>
      </div>`).join('') + '</div>';
  } catch (e) {
    g('k-list').innerHTML = '<div class="empty">Failed to load keys.</div>';
  }
}

function openNewKeyModal() {
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'new-key-modal';
  overlay.innerHTML = `<div class="modal">
    <h2>Create API Key</h2>
    <div class="modal-sub">Give this key a name to identify what system or agent uses it.</div>
    <label class="field">Name</label>
    <input id="nk-name" placeholder="e.g. ci-pipeline, agent-alpha, matt" autocomplete="off" />
    <div class="modal-buttons">
      <button class="modal-cancel" onclick="closeNewKeyModal()">Cancel</button>
      <button class="modal-confirm" id="nk-submit" onclick="submitNewKey()">Create</button>
    </div>
  </div>`;
  document.body.appendChild(overlay);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeNewKeyModal(); });
  g('nk-name').focus();
}

function closeNewKeyModal() {
  const m = g('new-key-modal');
  if (m) m.remove();
}

async function submitNewKey() {
  const name = g('nk-name').value.trim();
  if (!name) { g('nk-name').style.borderColor = 'var(--red)'; return; }
  const btn = g('nk-submit');
  btn.textContent = '...';
  btn.disabled = true;
  try {
    const res = await fetch('/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ name })
    });
    if (res.status === 401) { alert('Invalid API key. Enter a valid key to create new keys.'); return; }
    if (!res.ok) throw new Error('Failed');
    const key = await res.json();
    closeNewKeyModal();
    // Show the full key in a banner
    g('key-banner').innerHTML = `<div class="key-created-banner">
      <div style="font-size:13px;font-weight:600;margin-bottom:4px;">Key created for "${esc(key.name)}"</div>
      <div class="key-full">${esc(key.key)}</div>
      <div class="key-warn">Copy this key now — it will not be shown again in full.</div>
    </div>`;
    loadKeys();
  } catch (e) {
    btn.textContent = 'Retry';
    btn.disabled = false;
    alert('Failed to create key: ' + e.message);
  }
}

async function revokeKey(id, name) {
  if (!confirm('Revoke key "' + name + '"? Any system using it will lose write access.')) return;
  try {
    const res = await fetch('/keys/' + id, {
      method: 'DELETE',
      headers: authHeaders()
    });
    if (res.status === 401) { alert('Invalid API key.'); return; }
    if (!res.ok && res.status !== 204) throw new Error('Failed');
    loadKeys();
  } catch (e) {
    alert('Failed to revoke key: ' + e.message);
  }
}

function showHumanTasks() {
  g('t-user').value = 'human';
  g('t-status').value = 'pending';
  g('t-priority').value = '';
  g('t-search').value = '';
  tOffset = 0;
  switchTab('tasks');
}

// Initial load
loadPresence();
loadFilters();
loadStats();
loadProjects();
</script>
</body>
</html>
"""


@router.get("/ui", response_class=HTMLResponse)
def ui():
    return HTML
