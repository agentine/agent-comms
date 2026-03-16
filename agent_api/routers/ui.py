from datetime import datetime, timezone
from html import escape as _esc
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select, union
from sqlalchemy.orm import Session

from agent_api.database import (
    SessionLocal,
    agents,
    api_keys,
    journal,
    projects_table,
    tasks,
)

router = APIRouter(tags=["ui"])

PER_PAGE = 30


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ── Utilities ─────────────────────────────────────────────────────────


def esc(value) -> str:
    if value is None:
        return ""
    return _esc(str(value))


def time_ago(iso_str) -> str:
    if not iso_str:
        return ""
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        diff = (datetime.now(timezone.utc) - dt).total_seconds()
        if diff < 60:
            return "just now"
        if diff < 3600:
            return f"{int(diff // 60)}m ago"
        if diff < 86400:
            return f"{int(diff // 3600)}h ago"
        return f"{int(diff // 86400)}d ago"
    except Exception:
        return str(iso_str)


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def build_qs(**params) -> str:
    filtered = {k: v for k, v in params.items() if v is not None and v != ""}
    return urlencode(filtered, quote_via=quote) if filtered else ""


def check_api_key(db: Session, key: str) -> bool:
    has_keys = db.execute(select(api_keys.c.id).limit(1)).first()
    if not has_keys:
        return True  # no keys = open access
    if not key:
        return False
    row = db.execute(select(api_keys).where(api_keys.c.key == key)).first()
    return row is not None


# ── Status / Priority helpers ─────────────────────────────────────────


STATUS_COLORS = {
    "pending": ("bg-[#30363d]", "text-[#8b949e]"),
    "in_progress": ("bg-[#1a3a2a]", "text-[#3fb950]"),
    "blocked": ("bg-[#3d2a1a]", "text-[#d29922]"),
    "done": ("bg-[#1a2a3d]", "text-[#58a6ff]"),
    "cancelled": ("bg-[#3d1a1a]", "text-[#f85149]"),
}

PROJECT_STATUS_COLORS = {
    "discovery": ("bg-[#30363d]", "text-[#8b949e]"),
    "planning": ("bg-[#2a1a3d]", "text-[#bc8cff]"),
    "development": ("bg-[#1a3a2a]", "text-[#3fb950]"),
    "testing": ("bg-[#3d2a1a]", "text-[#d29922]"),
    "documentation": ("bg-[#1a2a3d]", "text-[#58a6ff]"),
    "published": ("bg-[#1a3a2a] border border-[#2a5a3a]", "text-[#3fb950]"),
    "maintained": ("bg-[#1a3a2a]", "text-[#3fb950]"),
}

LANG_COLORS = {
    "python": ("bg-[#1a2a1a]", "text-[#3fb950]"),
    "node": ("bg-[#2a2a1a]", "text-[#d29922]"),
    "javascript": ("bg-[#2a2a1a]", "text-[#d29922]"),
    "go": ("bg-[#1a2a3d]", "text-[#58a6ff]"),
}

PRIORITY_COLORS = {
    1: "text-[#8b949e]",
    2: "text-[#e6edf3]",
    3: "text-[#d29922]",
    4: "text-[#ff7b00]",
    5: "text-[#f85149]",
}


def status_badge(status: str) -> str:
    bg, fg = STATUS_COLORS.get(status, ("bg-[#30363d]", "text-[#8b949e]"))
    return f'<span class="inline-block px-2 py-0.5 rounded-xl text-[11px] font-semibold {bg} {fg}">{esc(status)}</span>'


def project_status_badge(status: str) -> str:
    bg, fg = PROJECT_STATUS_COLORS.get(status, ("bg-[#30363d]", "text-[#8b949e]"))
    return f'<span class="inline-block px-2 py-0.5 rounded-xl text-[11px] font-semibold {bg} {fg}">{esc(status)}</span>'


def lang_tag(language: str) -> str:
    bg, fg = LANG_COLORS.get(language, ("bg-[#30363d]", "text-[#8b949e]"))
    return f'<span class="px-1.5 py-0.5 rounded text-[11px] font-medium {bg} {fg}">{esc(language)}</span>'


def priority_label(p: int) -> str:
    color = PRIORITY_COLORS.get(p, "text-[#8b949e]")
    return f'<span class="font-bold text-xs {color}">P{p}</span>'


# ── Component Renderers ──────────────────────────────────────────────


def render_task_card(row) -> str:
    m = row._mapping
    is_human = m["username"] == "human"
    can_act = is_human and m["status"] not in ("done", "cancelled")

    action_btns = ""
    if can_act:
        action_btns = f"""
            <button class="bg-[#1a3a2a] text-[#3fb950] border border-[#2a5a3a] rounded-md px-2.5 py-0.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#2a4a3a]"
                    onclick="openActionModal({m['id']},'done')">Mark Done</button>
            <button class="bg-[#3d1a1a] text-[#f85149] border border-[#5a2a2a] rounded-md px-2.5 py-0.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#4a2a2a]"
                    onclick="openActionModal({m['id']},'cancelled')">Reject</button>"""

    project_html = ""
    if m["project"]:
        pq = build_qs(project=m["project"])
        project_html = f"""
            <a class="bg-[#1a2a3d] text-[#58a6ff] px-1.5 py-0.5 rounded text-[11px] no-underline hover:underline cursor-pointer"
               hx-get="/ui/tasks?{pq}" hx-target="#tab-content" hx-push-url="true">{esc(m['project'])}</a>
            <a href="https://github.com/agentine/{quote(m['project'])}" target="_blank"
               class="text-[#8b949e] text-[11px] no-underline hover:text-[#58a6ff]">&#x2197;</a>"""

    desc_html = ""
    if m.get("description"):
        desc_html = f'<div class="text-sm whitespace-pre-wrap break-words mt-1.5">{esc(m["description"])}</div>'

    return f"""<div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-3 mb-2" id="task-{m['id']}">
  <div class="flex justify-between items-center mb-1">
    <div class="flex items-center gap-2">
      <span class="text-[#8b949e] text-xs font-mono cursor-pointer hover:text-[#58a6ff]"
            title="Click to copy #{m['id']}" onclick="navigator.clipboard.writeText('#{m['id']}')">#{m['id']}</span>
      {priority_label(m['priority'])}
      {status_badge(m['status'])}
      <span class="text-[15px] font-semibold">{esc(m['title'])}</span>
    </div>
    <div class="flex items-center gap-2 text-xs text-[#8b949e]">
      <span class="text-[#bc8cff] font-semibold text-[13px]">{esc(m['username'])}</span>
      {action_btns}
    </div>
  </div>
  <div class="flex items-center gap-3 flex-wrap text-xs text-[#8b949e] mt-1">
    {project_html}
    <span title="{esc(m['created_at'])}">created {time_ago(m['created_at'])}</span>
    <span title="{esc(m['updated_at'])}">updated {time_ago(m['updated_at'])}</span>
  </div>
  {desc_html}
</div>"""


def render_journal_card(row) -> str:
    m = row._mapping
    project_html = ""
    if m["project"]:
        pq = build_qs(project=m["project"])
        project_html = f"""
            <a class="bg-[#1a2a3d] text-[#58a6ff] px-1.5 py-0.5 rounded text-[11px] no-underline hover:underline cursor-pointer"
               hx-get="/ui/journal?{pq}" hx-target="#tab-content" hx-push-url="true">{esc(m['project'])}</a>
            <a href="https://github.com/agentine/{quote(m['project'])}" target="_blank"
               class="text-[#8b949e] text-[11px] no-underline hover:text-[#58a6ff]">&#x2197;</a>"""

    return f"""<div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-3 mb-2">
  <div class="flex justify-between items-center mb-1">
    <div class="flex items-center gap-3 text-xs text-[#8b949e]">
      <span class="text-[#8b949e] text-xs font-mono">#{m['id']}</span>
      <span class="text-[#bc8cff] font-semibold text-[13px]">{esc(m['username'])}</span>
      {project_html}
    </div>
    <div class="text-xs text-[#8b949e]">
      <span title="{esc(m['created_at'])}">{time_ago(m['created_at'])}</span>
    </div>
  </div>
  <div class="text-sm whitespace-pre-wrap break-words mt-1.5">{esc(m['content'])}</div>
</div>"""


def render_project_row(p, task_counts: dict, journal_count: int) -> str:
    m = p._mapping
    tc = task_counts
    pend = tc.get("pending", 0)
    act = tc.get("in_progress", 0)
    blk = tc.get("blocked", 0)
    done = tc.get("done", 0)
    total = pend + act + blk + done + tc.get("cancelled", 0)

    name = m["name"]
    tc_html = '<span class="text-[#8b949e] text-xs">-</span>'
    if total > 0:
        parts = []
        if pend:
            pq = build_qs(project=name, status="pending")
            parts.append(
                f'<span class="bg-[#30363d] text-[#8b949e] px-1 py-0.5 rounded cursor-pointer hover:opacity-80"'
                f' hx-get="/ui/tasks?{pq}" hx-target="#tab-content" hx-push-url="true">{pend}p</span>'
            )
        if act:
            aq = build_qs(project=name, status="in_progress")
            parts.append(
                f'<span class="bg-[#1a3a2a] text-[#3fb950] px-1 py-0.5 rounded cursor-pointer hover:opacity-80"'
                f' hx-get="/ui/tasks?{aq}" hx-target="#tab-content" hx-push-url="true">{act}a</span>'
            )
        if blk:
            bq = build_qs(project=name, status="blocked")
            parts.append(
                f'<span class="bg-[#3d2a1a] text-[#d29922] px-1 py-0.5 rounded cursor-pointer hover:opacity-80"'
                f' hx-get="/ui/tasks?{bq}" hx-target="#tab-content" hx-push-url="true">{blk}b</span>'
            )
        if done:
            dq = build_qs(project=name, status="done")
            parts.append(
                f'<span class="bg-[#1a2a3d] text-[#58a6ff] px-1 py-0.5 rounded cursor-pointer hover:opacity-80"'
                f' hx-get="/ui/tasks?{dq}" hx-target="#tab-content" hx-push-url="true">{done}d</span>'
            )
        tc_html = f'<span class="text-[11px] inline-flex gap-1 flex-wrap">{"".join(parts)}</span>'

    jc_html = '<span class="text-[#8b949e] text-xs">-</span>'
    if journal_count > 0:
        jq = build_qs(project=name)
        jc_html = (
            f'<span class="text-[#8b949e] text-xs cursor-pointer hover:text-[#58a6ff] hover:underline"'
            f' hx-get="/ui/journal?{jq}" hx-target="#tab-content" hx-push-url="true">{journal_count}</span>'
        )

    desc_html = ""
    if m.get("description"):
        desc_html = f'<div class="text-[#8b949e] text-xs max-w-[200px] overflow-hidden text-ellipsis whitespace-nowrap" title="{esc(m["description"])}">{esc(m["description"])}</div>'

    return f"""<tr class="hover:bg-[rgba(88,166,255,0.04)]">
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle">
    <a class="font-semibold text-[#58a6ff] text-[13px] no-underline hover:underline"
       href="https://github.com/agentine/{quote(name)}" target="_blank">{esc(name)}</a>
    {desc_html}
  </td>
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle">{lang_tag(m['language'])}</td>
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle">{project_status_badge(m['status'])}</td>
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle">{tc_html}</td>
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle">{jc_html}</td>
  <td class="px-2.5 py-2 border-b border-[#30363d] align-middle text-xs text-[#8b949e] whitespace-nowrap"
      title="{esc(m['updated_at'])}">{time_ago(m['updated_at'])}</td>
</tr>"""


def render_key_row(row) -> str:
    m = row._mapping
    return f"""<div class="flex items-center gap-3 px-4 py-2.5 border-b border-[#30363d] last:border-b-0">
  <span class="font-semibold text-sm min-w-[120px]">{esc(m['name'])}</span>
  <span class="font-mono text-[13px] text-[#8b949e] bg-[#0d1117] px-2 py-0.5 rounded">{esc(m['key'])}</span>
  <span class="text-xs text-[#8b949e] ml-auto" title="{esc(m['created_at'])}">{time_ago(m['created_at'])}</span>
  <button class="bg-[#3d1a1a] text-[#f85149] border border-[#5a2a2a] rounded-md px-2.5 py-0.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#4a2a2a]"
          data-key-id="{m['id']}" data-key-name="{esc(m['name'])}"
          onclick="revokeKey(+this.dataset.keyId, this.dataset.keyName)">Revoke</button>
</div>"""


def render_pager(prefix: str, path: str, offset: int, total: int, **params) -> str:
    page = offset // PER_PAGE + 1
    pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)

    prev_disabled = "opacity-40 cursor-default pointer-events-none" if offset == 0 else ""
    next_disabled = (
        "opacity-40 cursor-default pointer-events-none"
        if offset + PER_PAGE >= total
        else ""
    )

    prev_offset = max(0, offset - PER_PAGE)
    next_offset = offset + PER_PAGE

    prev_qs = build_qs(offset=prev_offset, **params) if offset > 0 else ""
    next_qs = build_qs(offset=next_offset, **params)

    prev_label = "&larr; Newer" if prefix == "j" else "&larr; Prev"
    next_label = "Older &rarr;" if prefix == "j" else "Next &rarr;"

    return f"""<div class="flex gap-2 justify-center items-center mt-4">
  <button class="bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-3.5 py-1.5 rounded-md text-[13px] cursor-pointer {prev_disabled}"
          hx-get="{path}?{prev_qs}" hx-target="#tab-content" hx-push-url="true">{prev_label}</button>
  <span class="text-[13px] text-[#8b949e]">{page} / {pages}</span>
  <button class="bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-3.5 py-1.5 rounded-md text-[13px] cursor-pointer {next_disabled}"
          hx-get="{path}?{next_qs}" hx-target="#tab-content" hx-push-url="true">{next_label}</button>
</div>"""


# ── Filter Bar Renderers ─────────────────────────────────────────────

INPUT_CLS = "bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-2.5 py-1.5 rounded-md text-[13px] placeholder:text-[#8b949e]"
SELECT_CLS = "bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-2.5 py-1.5 rounded-md text-[13px] cursor-pointer"


def _search_input(name: str, value: str, placeholder: str, path: str) -> str:
    return f"""<div class="relative">
  <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#8b949e] text-[13px] pointer-events-none">&#x1F50D;</span>
  <input name="{name}" value="{esc(value)}" placeholder="{placeholder}" autocomplete="off"
         class="{INPUT_CLS} w-[220px] !pl-7"
         hx-get="{path}" hx-target="#tab-content" hx-trigger="input changed delay:300ms"
         hx-include="closest form" hx-push-url="true" />
</div>"""


def _select(name: str, value: str, options: list[tuple[str, str]], path: str) -> str:
    opts = []
    for val, label in options:
        sel = " selected" if val == value else ""
        opts.append(f'<option value="{esc(val)}"{sel}>{esc(label)}</option>')
    return f"""<select name="{name}" class="{SELECT_CLS}"
       hx-get="{path}" hx-target="#tab-content" hx-trigger="change"
       hx-include="closest form" hx-push-url="true">
  {"".join(opts)}
</select>"""


def _text_input(
    name: str, value: str, placeholder: str, path: str, datalist: str = ""
) -> str:
    dl = f' list="{datalist}"' if datalist else ""
    extra = ' data-1p-ignore data-lpignore="true" data-form-type="other"' if name in ("username",) else ""
    return f"""<input name="{name}" value="{esc(value)}" placeholder="{placeholder}" autocomplete="off"
       class="{INPUT_CLS}"{dl}{extra}
       hx-get="{path}" hx-target="#tab-content" hx-trigger="input changed delay:300ms"
       hx-include="closest form" hx-push-url="true" />"""


# ── Tab Content Renderers ─────────────────────────────────────────────


def render_projects_tab(db: Session, search: str, status: str, language: str, offset: int) -> str:
    query = select(projects_table)
    count_query = select(func.count()).select_from(projects_table)

    if status:
        query = query.where(projects_table.c.status == status)
        count_query = count_query.where(projects_table.c.status == status)
    if language:
        query = query.where(projects_table.c.language == language)
        count_query = count_query.where(projects_table.c.language == language)
    if search:
        term = f"%{search}%"
        cond = projects_table.c.name.like(term) | projects_table.c.description.like(term)
        query = query.where(cond)
        count_query = count_query.where(cond)

    total = db.execute(count_query).scalar() or 0
    rows = db.execute(
        query.order_by(projects_table.c.updated_at.desc()).limit(PER_PAGE).offset(offset)
    ).fetchall()

    project_names = [r._mapping["name"] for r in rows]

    task_counts_map: dict[str, dict[str, int]] = {}
    if project_names:
        tc_rows = db.execute(
            select(tasks.c.project, tasks.c.status, func.count())
            .where(tasks.c.project.in_(project_names))
            .group_by(tasks.c.project, tasks.c.status)
        ).all()
        for proj, st, cnt in tc_rows:
            task_counts_map.setdefault(proj, {})[st] = cnt

    journal_counts_map: dict[str, int] = {}
    if project_names:
        jc_rows = db.execute(
            select(journal.c.project, func.count())
            .where(journal.c.project.in_(project_names))
            .group_by(journal.c.project)
        ).all()
        journal_counts_map = {proj: cnt for proj, cnt in jc_rows}

    path = "/ui/projects"
    status_options = [
        ("", "all statuses"),
        ("discovery", "discovery"),
        ("planning", "planning"),
        ("development", "development"),
        ("testing", "testing"),
        ("documentation", "documentation"),
        ("published", "published"),
        ("maintained", "maintained"),
    ]
    lang_options = [
        ("", "all languages"),
        ("python", "python"),
        ("node", "node"),
        ("go", "go"),
    ]

    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search projects...", path)}
  {_select("status", status, status_options, path)}
  {_select("language", language, lang_options, path)}
</form>"""

    if rows:
        table_rows = "".join(
            render_project_row(r, task_counts_map.get(r._mapping["name"], {}), journal_counts_map.get(r._mapping["name"], 0))
            for r in rows
        )
        list_html = f"""<div class="overflow-x-auto">
  <table class="w-full border-collapse text-[13px]">
    <thead><tr>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Project</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Lang</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Status</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Tasks</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Journal</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#30363d] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Updated</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>"""
    else:
        list_html = '<div class="text-center text-[#8b949e] py-10 text-sm">No projects found</div>'

    params = dict(search=search, status=status, language=language)
    pager_html = render_pager("p", path, offset, total, **params)

    return f"""{filters_html}
<div class="text-[13px] text-[#8b949e] mb-3">{total} {"item" if total == 1 else "items"}</div>
{list_html}
{pager_html}"""


def render_tasks_tab(
    db: Session,
    search: str,
    username: str,
    project: str,
    status: str,
    priority: str,
    sort: str,
    offset: int,
) -> str:
    # Fetch filter options for datalists
    usernames = sorted(
        db.execute(
            union(select(agents.c.username), select(tasks.c.username))
        ).scalars().all()
    )
    projects_list = sorted(
        db.execute(
            union(
                select(tasks.c.project).where(tasks.c.project.isnot(None)),
                select(agents.c.project).where(agents.c.project.isnot(None)),
            )
        ).scalars().all()
    )

    # Check for direct task ID lookup
    id_match = None
    if search and search.startswith("#") and search[1:].isdigit():
        id_match = int(search[1:])

    if id_match is not None:
        row = db.execute(select(tasks).where(tasks.c.id == id_match)).first()
        if row:
            items_html = render_task_card(row)
            total = 1
        else:
            items_html = f'<div class="text-center text-[#8b949e] py-10 text-sm">Task {esc(search)} not found</div>'
            total = 0
    else:
        query = select(tasks)
        count_query = select(func.count()).select_from(tasks)

        if username:
            query = query.where(tasks.c.username == username)
            count_query = count_query.where(tasks.c.username == username)
        if project:
            query = query.where(tasks.c.project == project)
            count_query = count_query.where(tasks.c.project == project)
        if status:
            query = query.where(tasks.c.status == status)
            count_query = count_query.where(tasks.c.status == status)
        if priority:
            query = query.where(tasks.c.priority == int(priority))
            count_query = count_query.where(tasks.c.priority == int(priority))
        if search:
            term = f"%{search}%"
            cond = tasks.c.title.like(term) | tasks.c.description.like(term)
            query = query.where(cond)
            count_query = count_query.where(cond)

        order = tasks.c.created_at.asc() if sort == "asc" else tasks.c.created_at.desc()
        total = db.execute(count_query).scalar() or 0
        rows = db.execute(query.order_by(order).limit(PER_PAGE).offset(offset)).fetchall()

        if rows:
            items_html = "".join(render_task_card(r) for r in rows)
        else:
            items_html = '<div class="text-center text-[#8b949e] py-10 text-sm">No tasks</div>'

    path = "/ui/tasks"
    status_options = [
        ("", "all statuses"),
        ("pending", "pending"),
        ("in_progress", "in_progress"),
        ("blocked", "blocked"),
        ("done", "done"),
        ("cancelled", "cancelled"),
    ]
    priority_options = [
        ("", "all priorities"),
        ("5", "P5 (highest)"),
        ("4", "P4"),
        ("3", "P3"),
        ("2", "P2"),
        ("1", "P1 (lowest)"),
    ]
    sort_options = [("desc", "Newest first"), ("asc", "Oldest first")]

    dl_users = "".join(f'<option value="{esc(u)}">' for u in usernames)
    dl_projects = "".join(f'<option value="{esc(p)}">' for p in projects_list)

    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search or #id...", path)}
  {_text_input("username", username, "agent", path, "dl-users")}
  {_text_input("project", project, "project", path, "dl-projects")}
  {_select("status", status, status_options, path)}
  {_select("priority", priority, priority_options, path)}
  {_select("sort", sort, sort_options, path)}
  <button type="button" class="bg-[#58a6ff] text-black border-none rounded-md px-3.5 py-1.5 text-[13px] font-semibold cursor-pointer hover:opacity-90"
          onclick="openNewTaskModal()">+ New Task</button>
</form>
<datalist id="dl-users">{dl_users}</datalist>
<datalist id="dl-projects">{dl_projects}</datalist>"""

    params = dict(search=search, username=username, project=project, status=status, priority=priority, sort=sort)
    pager_html = render_pager("t", path, offset, total, **params)

    return f"""{filters_html}
<div class="text-[13px] text-[#8b949e] mb-3">{total} {"item" if total == 1 else "items"}</div>
{items_html}
{pager_html}"""


def render_journal_tab(
    db: Session,
    search: str,
    username: str,
    project: str,
    sort: str,
    offset: int,
) -> str:
    usernames = sorted(
        db.execute(
            union(select(agents.c.username), select(journal.c.username))
        ).scalars().all()
    )
    projects_list = sorted(
        db.execute(
            union(
                select(journal.c.project).where(journal.c.project.isnot(None)),
                select(agents.c.project).where(agents.c.project.isnot(None)),
            )
        ).scalars().all()
    )

    query = select(journal)
    count_query = select(func.count()).select_from(journal)

    if username:
        query = query.where(journal.c.username == username)
        count_query = count_query.where(journal.c.username == username)
    if project:
        query = query.where(journal.c.project == project)
        count_query = count_query.where(journal.c.project == project)
    if search:
        term = f"%{search}%"
        query = query.where(journal.c.content.like(term))
        count_query = count_query.where(journal.c.content.like(term))

    order = journal.c.created_at.asc() if sort == "asc" else journal.c.created_at.desc()
    total = db.execute(count_query).scalar() or 0
    rows = db.execute(query.order_by(order).limit(PER_PAGE).offset(offset)).fetchall()

    if rows:
        items_html = "".join(render_journal_card(r) for r in rows)
    else:
        items_html = '<div class="text-center text-[#8b949e] py-10 text-sm">No journal entries</div>'

    path = "/ui/journal"
    sort_options = [("desc", "Newest first"), ("asc", "Oldest first")]

    dl_users = "".join(f'<option value="{esc(u)}">' for u in usernames)
    dl_projects = "".join(f'<option value="{esc(p)}">' for p in projects_list)

    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search content...", path)}
  {_text_input("username", username, "agent", path, "dl-users")}
  {_text_input("project", project, "project", path, "dl-projects")}
  {_select("sort", sort, sort_options, path)}
</form>
<datalist id="dl-users">{dl_users}</datalist>
<datalist id="dl-projects">{dl_projects}</datalist>"""

    params = dict(search=search, username=username, project=project, sort=sort)
    pager_html = render_pager("j", path, offset, total, **params)

    return f"""{filters_html}
<div class="text-[13px] text-[#8b949e] mb-3">{total} {"item" if total == 1 else "items"}</div>
{items_html}
{pager_html}"""


def render_keys_tab(db: Session, api_key: str) -> str:
    authed = check_api_key(db, api_key)

    btn = """<div class="flex gap-2 mb-4 flex-wrap items-center">
  <button type="button" class="bg-[#58a6ff] text-black border-none rounded-md px-3.5 py-1.5 text-[13px] font-semibold cursor-pointer hover:opacity-90"
          onclick="openNewKeyModal()">+ New Key</button>
</div>"""

    if not authed:
        return f"""{btn}
<div id="key-banner"></div>
<div class="text-center text-[#8b949e] py-10 text-sm">Enter a valid API key above to manage keys.</div>"""

    rows = db.execute(
        select(api_keys).order_by(api_keys.c.created_at.desc())
    ).fetchall()

    # Mask keys - show only first 8 chars
    class MaskedRow:
        def __init__(self, row):
            m = dict(row._mapping)
            m["key"] = m["key"][:8] + "..."
            self._mapping = m

    total = len(rows)
    if rows:
        items_html = '<div class="bg-[#161b22] border border-[#30363d] rounded-lg overflow-hidden">'
        items_html += "".join(render_key_row(MaskedRow(r)) for r in rows)
        items_html += "</div>"
    else:
        items_html = '<div class="text-center text-[#8b949e] py-10 text-sm">No API keys. Auth is currently disabled (open access).</div>'

    return f"""{btn}
<div id="key-banner"></div>
<div class="text-[13px] text-[#8b949e] mb-3">{total} {"key" if total == 1 else "keys"}</div>
{items_html}"""


# ── Stats & Presence Partials ─────────────────────────────────────────


def render_stats_html(db: Session) -> str:
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
    ).scalar() or 0

    pending = task_counts.get("pending", 0)
    in_progress = task_counts.get("in_progress", 0)
    blocked = task_counts.get("blocked", 0)
    done = task_counts.get("done", 0)
    cancelled = task_counts.get("cancelled", 0)

    human_card = ""
    if human_actionable > 0:
        hq = build_qs(username="human", status="pending")
        human_card = f"""<div class="bg-[#161b22] border border-[#d29922] rounded-lg px-4 py-2.5 flex flex-col min-w-[100px] cursor-pointer hover:bg-[#2a2210]"
     hx-get="/ui/tasks?{hq}" hx-target="#tab-content" hx-push-url="true" title="Click to view pending human tasks">
  <span class="text-[22px] font-bold leading-tight text-[#d29922]">{human_actionable}</span>
  <span class="text-[11px] text-[#d29922] uppercase tracking-wider">Human Action Needed</span>
</div>"""

    return f"""<div class="flex gap-4 flex-wrap">
  <div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-2.5 flex flex-col min-w-[100px]">
    <span class="text-[22px] font-bold leading-tight">{total_tasks}</span>
    <span class="text-[11px] text-[#8b949e] uppercase tracking-wider">Tasks</span>
    <div class="flex gap-2.5 mt-1 text-[11px] text-[#8b949e]">
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-[#8b949e] inline-block"></span>{pending} pending</span>
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-[#3fb950] inline-block"></span>{in_progress} active</span>
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-[#d29922] inline-block"></span>{blocked} blocked</span>
    </div>
  </div>
  <div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-2.5 flex flex-col min-w-[100px]">
    <span class="text-[22px] font-bold leading-tight">{done}</span>
    <span class="text-[11px] text-[#8b949e] uppercase tracking-wider">Completed</span>
    <div class="flex gap-2.5 mt-1 text-[11px] text-[#8b949e]">
      <span class="flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-[#f85149] inline-block"></span>{cancelled} cancelled</span>
    </div>
  </div>
  <div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-2.5 flex flex-col min-w-[100px]">
    <span class="text-[22px] font-bold leading-tight">{running_agents} <span class="text-[13px] font-normal text-[#8b949e]">/ {agent_count}</span></span>
    <span class="text-[11px] text-[#8b949e] uppercase tracking-wider">Agents Online</span>
  </div>
  <div class="bg-[#161b22] border border-[#30363d] rounded-lg px-4 py-2.5 flex flex-col min-w-[100px]">
    <span class="text-[22px] font-bold leading-tight">{journal_count}</span>
    <span class="text-[11px] text-[#8b949e] uppercase tracking-wider">Journal Entries</span>
  </div>
  {human_card}
</div>"""


def render_presence_html(db: Session) -> str:
    rows = db.execute(
        select(agents).order_by(agents.c.updated_at.desc())
    ).fetchall()

    if not rows:
        return '<span class="text-xs text-[#8b949e] italic">no agents online</span>'

    items = []
    for row in rows:
        m = row._mapping
        dot_cls = "bg-[#3fb950] shadow-[0_0_4px_#3fb950]" if m["status"] == "running" else "bg-[#8b949e]"
        project_html = ""
        if m["project"]:
            project_html = f' <a class="text-[#8b949e] text-[11px] no-underline hover:underline" href="https://github.com/agentine/{quote(m["project"])}" target="_blank">{esc(m["project"])}</a>'
        items.append(
            f'<span class="inline-flex items-center gap-1.5 bg-[#161b22] border border-[#30363d] rounded-full px-2.5 py-0.5 text-xs font-medium">'
            f'<span class="w-[7px] h-[7px] rounded-full shrink-0 {dot_cls}"></span>'
            f'<span>{esc(m["username"])}</span>'
            f'{project_html}'
            f'</span>'
        )
    return "".join(items)


# ── Tab Bar ───────────────────────────────────────────────────────────


def render_tab_bar(active: str) -> str:
    tabs_def = [
        ("projects", "Projects"),
        ("tasks", "Tasks"),
        ("journal", "Journal"),
        ("keys", "Keys"),
    ]
    items = []
    for tab_id, label in tabs_def:
        active_cls = "text-[#e6edf3] !border-b-[#58a6ff]" if tab_id == active else ""
        items.append(
            f'<button class="px-4 py-2 text-[#8b949e] border-b-2 border-transparent text-sm font-medium bg-transparent'
            f" border-t-0 border-l-0 border-r-0 cursor-pointer hover:text-[#e6edf3] {active_cls}\""
            f' hx-get="/ui/{tab_id}" hx-target="#tab-content" hx-push-url="true">{label}</button>'
        )
    return "".join(items)


def render_tab_bar_oob(active: str) -> str:
    return f'<div id="tab-bar" hx-swap-oob="innerHTML">{render_tab_bar(active)}</div>'


# ── Shell & Landing Page ─────────────────────────────────────────────

CLIENT_JS = """
function getApiKey() { return localStorage.getItem('agent_comms_api_key') || ''; }
function saveApiKey() {
  var key = document.getElementById('api-key').value.trim();
  if (key) { localStorage.setItem('agent_comms_api_key', key); }
  else { localStorage.removeItem('agent_comms_api_key'); }
  var st = document.getElementById('api-key-status');
  st.textContent = key ? 'Saved' : 'Cleared';
  setTimeout(function() { st.textContent = ''; }, 2000);
}
document.addEventListener('DOMContentLoaded', function() {
  var saved = getApiKey();
  if (saved) { document.getElementById('api-key').value = saved; }
});

// Inject API key header on all htmx requests
document.addEventListener('htmx:configRequest', function(evt) {
  var key = getApiKey();
  if (key) { evt.detail.headers['X-API-Key'] = key; }
});

// Task action modal
var actionTaskId = null, actionStatus = null;
function openActionModal(taskId, status) {
  actionTaskId = taskId;
  actionStatus = status;
  var isDone = status === 'done';
  var overlay = document.createElement('div');
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50';
  overlay.id = 'action-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#30363d] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">' + (isDone ? 'Mark Task Done' : 'Reject Task') + '</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">' + (isDone ? 'Provide a brief summary of what was completed.' : 'Provide a reason for rejecting this task.') + '</div>' +
    '<textarea id="action-summary" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px] font-[inherit] resize-y min-h-[80px]" placeholder="' + (isDone ? 'Summary of work done...' : 'Reason for rejection...') + '"></textarea>' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#30363d] text-[#e6edf3] px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" onclick="closeActionModal()">Cancel</button>' +
    '<button class="' + (isDone ? 'bg-[#3fb950] text-black' : 'bg-[#f85149] text-white') + ' px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" id="action-submit" onclick="submitAction()">' + (isDone ? 'Complete' : 'Reject') + '</button>' +
    '</div></div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) closeActionModal(); });
  document.getElementById('action-summary').focus();
}
function closeActionModal() {
  var m = document.getElementById('action-modal');
  if (m) m.remove();
  actionTaskId = null; actionStatus = null;
}
async function submitAction() {
  var summary = document.getElementById('action-summary').value.trim();
  if (!summary) { document.getElementById('action-summary').style.borderColor = '#f85149'; return; }
  var btn = document.getElementById('action-submit');
  btn.textContent = '...'; btn.disabled = true;
  try {
    var res = await fetch('/tasks/' + actionTaskId, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': getApiKey() },
      body: JSON.stringify({ status: actionStatus, description: summary })
    });
    if (!res.ok) throw new Error('Failed');
    closeActionModal();
    htmx.ajax('GET', window.location.pathname + window.location.search, {target: '#tab-content', swap: 'innerHTML'});
  } catch (e) {
    btn.textContent = 'Retry'; btn.disabled = false;
    alert('Failed to update task: ' + e.message);
  }
}

// New task modal
function openNewTaskModal() {
  var overlay = document.createElement('div');
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50';
  overlay.id = 'new-task-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#30363d] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">New Task</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">Assign a task to an agent or team member.</div>' +
    '<label class="block text-xs text-[#8b949e] mb-1">Assign to</label>' +
    '<input id="nt-user" list="dl-users" placeholder="agent" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px] mb-2" />' +
    '<label class="block text-xs text-[#8b949e] mb-1">Title</label>' +
    '<input id="nt-title" placeholder="Task title" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px] mb-2" />' +
    '<div class="flex gap-2.5">' +
    '<div class="flex-1"><label class="block text-xs text-[#8b949e] mb-1">Priority</label>' +
    '<select id="nt-priority" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px]">' +
    '<option value="1">P1 (lowest)</option><option value="2">P2</option><option value="3" selected>P3</option><option value="4">P4</option><option value="5">P5 (highest)</option></select></div>' +
    '<div class="flex-1"><label class="block text-xs text-[#8b949e] mb-1">Project</label>' +
    '<input id="nt-project" list="dl-projects" placeholder="optional" autocomplete="off" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px]" /></div></div>' +
    '<label class="block text-xs text-[#8b949e] mb-1 mt-2.5">Description</label>' +
    '<textarea id="nt-desc" placeholder="Describe what needs to be done..." class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px] font-[inherit] resize-y min-h-[80px]"></textarea>' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#30363d] text-[#e6edf3] px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" onclick="closeNewTaskModal()">Cancel</button>' +
    '<button class="bg-[#3fb950] text-black px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" id="nt-submit" onclick="submitNewTask()">Create Task</button>' +
    '</div></div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) closeNewTaskModal(); });
  document.getElementById('nt-user').focus();
}
function closeNewTaskModal() {
  var m = document.getElementById('new-task-modal');
  if (m) m.remove();
}
async function submitNewTask() {
  var user = document.getElementById('nt-user').value.trim();
  var title = document.getElementById('nt-title').value.trim();
  if (!user) { document.getElementById('nt-user').style.borderColor = '#f85149'; return; }
  if (!title) { document.getElementById('nt-title').style.borderColor = '#f85149'; return; }
  var btn = document.getElementById('nt-submit');
  btn.textContent = '...'; btn.disabled = true;
  var body = { username: user, title: title, priority: parseInt(document.getElementById('nt-priority').value) };
  var project = document.getElementById('nt-project').value.trim();
  if (project) body.project = project;
  var desc = document.getElementById('nt-desc').value.trim();
  if (desc) body.description = desc;
  try {
    var res = await fetch('/tasks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': getApiKey() },
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error('Failed');
    closeNewTaskModal();
    htmx.ajax('GET', window.location.pathname + window.location.search, {target: '#tab-content', swap: 'innerHTML'});
    htmx.ajax('GET', '/ui/partials/stats', {target: '#stats-bar', swap: 'innerHTML'});
  } catch (e) {
    btn.textContent = 'Retry'; btn.disabled = false;
    alert('Failed to create task: ' + e.message);
  }
}

// Keys management
function openNewKeyModal() {
  var overlay = document.createElement('div');
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50';
  overlay.id = 'new-key-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#30363d] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">Create API Key</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">Give this key a name to identify what system or agent uses it.</div>' +
    '<label class="block text-xs text-[#8b949e] mb-1">Name</label>' +
    '<input id="nk-name" placeholder="e.g. ci-pipeline, agent-alpha, matt" autocomplete="off" class="w-full bg-[#0d1117] border border-[#30363d] text-[#e6edf3] rounded-md p-2 text-[13px]" />' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#30363d] text-[#e6edf3] px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" onclick="closeNewKeyModal()">Cancel</button>' +
    '<button class="bg-[#3fb950] text-black px-4 py-1.5 rounded-md text-[13px] font-semibold cursor-pointer border-none" id="nk-submit" onclick="submitNewKey()">Create</button>' +
    '</div></div>';
  document.body.appendChild(overlay);
  overlay.addEventListener('click', function(e) { if (e.target === overlay) closeNewKeyModal(); });
  document.getElementById('nk-name').focus();
}
function closeNewKeyModal() {
  var m = document.getElementById('new-key-modal');
  if (m) m.remove();
}
async function submitNewKey() {
  var name = document.getElementById('nk-name').value.trim();
  if (!name) { document.getElementById('nk-name').style.borderColor = '#f85149'; return; }
  var btn = document.getElementById('nk-submit');
  btn.textContent = '...'; btn.disabled = true;
  try {
    var res = await fetch('/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-API-Key': getApiKey() },
      body: JSON.stringify({ name: name })
    });
    if (res.status === 401) { btn.textContent = 'Create'; btn.disabled = false; alert('Invalid API key. Enter a valid key to create new keys.'); return; }
    if (!res.ok) throw new Error('Failed');
    var key = await res.json();
    closeNewKeyModal();
    var banner = document.getElementById('key-banner');
    if (banner) {
      banner.innerHTML = '<div class="bg-[#1a3a2a] border border-[#2a5a3a] rounded-lg px-4 py-3 mb-3">' +
        '<div class="text-[13px] font-semibold mb-1">Key created for \\u201c' + name.replace(/[<>&"]/g, '') + '\\u201d</div>' +
        '<div class="font-mono text-[13px] text-[#3fb950] break-all select-all">' + key.key + '</div>' +
        '<div class="text-xs text-[#d29922] mt-1">Copy this key now \\u2014 it will not be shown again in full.</div></div>';
    }
    htmx.ajax('GET', '/ui/keys', {target: '#tab-content', swap: 'innerHTML'});
  } catch (e) {
    btn.textContent = 'Retry'; btn.disabled = false;
    alert('Failed to create key: ' + e.message);
  }
}
async function revokeKey(id, name) {
  if (!confirm('Revoke key "' + name + '"? Any system using it will lose write access.')) return;
  try {
    var res = await fetch('/keys/' + id, {
      method: 'DELETE',
      headers: { 'X-API-Key': getApiKey() }
    });
    if (res.status === 401) { alert('Invalid API key.'); return; }
    if (!res.ok && res.status !== 204) throw new Error('Failed');
    htmx.ajax('GET', '/ui/keys', {target: '#tab-content', swap: 'innerHTML'});
  } catch (e) {
    alert('Failed to revoke key: ' + e.message);
  }
}
"""


def render_shell(active_tab: str, content: str, stats_html: str, presence_html: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agent Comms</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body class="bg-[#0d1117] text-[#e6edf3] font-[-apple-system,BlinkMacSystemFont,'Segoe_UI',Helvetica,Arial,sans-serif] leading-relaxed">
<div class="max-w-[960px] mx-auto px-4 py-6">
  <div class="flex items-center justify-between mb-4">
    <h1 class="text-xl font-semibold">Agent Comms</h1>
    <a href="https://github.com/agentine" target="_blank"
       class="text-[#8b949e] hover:text-[#e6edf3] text-sm no-underline flex items-center gap-1">
      <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
      GitHub
    </a>
  </div>

  <div class="flex gap-2 items-center mb-3">
    <input id="api-key" type="password" placeholder="API key (required for writes)" autocomplete="off"
           class="bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-2.5 py-1.5 rounded-md text-[13px] w-[280px] placeholder:text-[#8b949e]" />
    <button onclick="saveApiKey()"
            class="bg-[#161b22] border border-[#30363d] text-[#e6edf3] px-2.5 py-1.5 rounded-md text-[13px] cursor-pointer">Save</button>
    <span id="api-key-status" class="text-xs text-[#8b949e]"></span>
  </div>

  <div class="flex items-center gap-3 mb-4 flex-wrap min-h-[28px]">
    <span class="text-xs text-[#8b949e] font-semibold uppercase tracking-wider mr-1">Agents</span>
    <span id="presence-bar" class="contents"
          hx-get="/ui/partials/presence" hx-trigger="every 5s" hx-swap="innerHTML">
      {presence_html}
    </span>
  </div>

  <div id="stats-bar" class="mb-4" hx-get="/ui/partials/stats" hx-trigger="every 5s" hx-swap="innerHTML">
    {stats_html}
  </div>

  <div class="flex border-b border-[#30363d] mb-4" id="tab-bar">
    {render_tab_bar(active_tab)}
  </div>

  <div id="tab-content">
    {content}
  </div>
</div>
<script>{CLIENT_JS}</script>
</body>
</html>"""


LANDING_PAGE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentine</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#0d1117] text-[#e6edf3] font-[-apple-system,BlinkMacSystemFont,'Segoe_UI',Helvetica,Arial,sans-serif] min-h-screen flex items-center justify-center">
<div class="max-w-2xl mx-auto px-6 py-16 text-center">
  <h1 class="text-4xl font-bold mb-3">Agentine</h1>
  <p class="text-[#8b949e] text-lg mb-10 max-w-md mx-auto">
    Agent communication platform &mdash; coordinate tasks, share journals, and monitor agent activity.
  </p>
  <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
    <a href="/ui"
       class="bg-[#161b22] border border-[#30363d] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors">
      <div class="text-2xl mb-2">&#x1F4CA;</div>
      <div class="font-semibold mb-1">Dashboard</div>
      <div class="text-sm text-[#8b949e]">View projects, tasks, and agent activity</div>
    </a>
    <a href="/docs"
       class="bg-[#161b22] border border-[#30363d] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors">
      <div class="text-2xl mb-2">&#x1F4D6;</div>
      <div class="font-semibold mb-1">API Docs</div>
      <div class="text-sm text-[#8b949e]">Interactive API documentation</div>
    </a>
    <a href="https://github.com/agentine" target="_blank"
       class="bg-[#161b22] border border-[#30363d] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors">
      <div class="text-2xl mb-2">
        <svg class="w-7 h-7 mx-auto" fill="currentColor" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
      </div>
      <div class="font-semibold mb-1">GitHub</div>
      <div class="text-sm text-[#8b949e]">Source code and projects</div>
    </a>
  </div>
</div>
</body>
</html>"""


# ── Routes ────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse)
def landing_page():
    return LANDING_PAGE


@router.get("/ui")
def ui_redirect():
    return RedirectResponse(url="/ui/projects", status_code=302)


@router.get("/ui/projects", response_class=HTMLResponse)
def ui_projects_page(
    request: Request,
    search: str = Query(default="", max_length=200),
    status: str = Query(default=""),
    language: str = Query(default=""),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    content = render_projects_tab(db, search, status, language, offset)
    if is_htmx(request):
        return HTMLResponse(content + render_tab_bar_oob("projects"))
    stats_html = render_stats_html(db)
    presence_html = render_presence_html(db)
    return HTMLResponse(render_shell("projects", content, stats_html, presence_html))


@router.get("/ui/tasks", response_class=HTMLResponse)
def ui_tasks_page(
    request: Request,
    search: str = Query(default="", max_length=200),
    username: str = Query(default=""),
    project: str = Query(default=""),
    status: str = Query(default=""),
    priority: str = Query(default=""),
    sort: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    content = render_tasks_tab(db, search, username, project, status, priority, sort, offset)
    if is_htmx(request):
        return HTMLResponse(content + render_tab_bar_oob("tasks"))
    stats_html = render_stats_html(db)
    presence_html = render_presence_html(db)
    return HTMLResponse(render_shell("tasks", content, stats_html, presence_html))


@router.get("/ui/journal", response_class=HTMLResponse)
def ui_journal_page(
    request: Request,
    search: str = Query(default="", max_length=200),
    username: str = Query(default=""),
    project: str = Query(default=""),
    sort: str = Query(default="desc"),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    content = render_journal_tab(db, search, username, project, sort, offset)
    if is_htmx(request):
        return HTMLResponse(content + render_tab_bar_oob("journal"))
    stats_html = render_stats_html(db)
    presence_html = render_presence_html(db)
    return HTMLResponse(render_shell("journal", content, stats_html, presence_html))


@router.get("/ui/keys", response_class=HTMLResponse)
def ui_keys_page(
    request: Request,
    x_api_key: str = Header(default=""),
    db: Session = Depends(get_db),
):
    content = render_keys_tab(db, x_api_key)
    if is_htmx(request):
        return HTMLResponse(content + render_tab_bar_oob("keys"))
    # For direct navigation, wrap in shell; keys will re-fetch via htmx if key is in localStorage
    stats_html = render_stats_html(db)
    presence_html = render_presence_html(db)
    shell = render_shell("keys", content, stats_html, presence_html)
    # Inject a script to re-fetch keys with the stored API key
    reload_script = """<script>
if (localStorage.getItem('agent_comms_api_key')) {
  document.addEventListener('DOMContentLoaded', function() {
    htmx.ajax('GET', '/ui/keys', {target: '#tab-content', swap: 'innerHTML'});
  });
}
</script>"""
    shell = shell.replace("</body>", reload_script + "</body>")
    return HTMLResponse(shell)


# ── Partial Endpoints ─────────────────────────────────────────────────


@router.get("/ui/partials/stats", response_class=HTMLResponse)
def ui_partials_stats(db: Session = Depends(get_db)):
    return HTMLResponse(render_stats_html(db))


@router.get("/ui/partials/presence", response_class=HTMLResponse)
def ui_partials_presence(db: Session = Depends(get_db)):
    return HTMLResponse(render_presence_html(db))


# ── JSON Endpoints (backward compat) ─────────────────────────────────


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
