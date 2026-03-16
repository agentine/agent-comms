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


def time_tag(iso_str) -> str:
    """Render a timestamp as a styled tooltip span."""
    ago = time_ago(iso_str)
    if not ago:
        return ""
    return f'<span class="timestamp text-xs text-[#8b949e] cursor-default" data-ts="{esc(iso_str)}">{ago}</span>'


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


# ── SVG Icons ─────────────────────────────────────────────────────────

ICONS = {
    "chevron-down": '<svg class="w-4 h-4 pointer-events-none" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M6 9l6 6 6-6"/></svg>',
    "x": '<svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 6L6 18M6 6l12 12"/></svg>',
    "inbox": '<svg class="w-10 h-10 text-[#30363d]" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7"/><path d="M2 13h6l2 3h4l2-3h6v5a2 2 0 01-2 2H4a2 2 0 01-2-2v-5z"/></svg>',
    "dashboard": '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></svg>',
    "folder": '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>',
    "tasks": '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/></svg>',
    "journal": '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M2 3h6a4 4 0 014 4v14a3 3 0 00-3-3H2z"/><path d="M22 3h-6a4 4 0 00-4 4v14a3 3 0 013-3h7z"/></svg>',
    "key": '<svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>',
    "search": '<svg class="w-4 h-4" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>',
    "external": '<svg class="w-3 h-3 inline-block" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
    "alert": '<svg class="w-5 h-5 shrink-0" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
    "menu": '<svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>',
    "github": '<svg class="w-4 h-4" fill="currentColor" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>',
    "chart": '<svg class="w-7 h-7" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M18 20V10"/><path d="M12 20V4"/><path d="M6 20v-6"/></svg>',
    "book": '<svg class="w-7 h-7" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>',
}


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
  <div class="flex gap-2 mt-3 pt-3 border-t border-[#1e2733]">
    <button class="bg-[#1a3a2a] text-[#3fb950] border border-[#2a5a3a] rounded-lg px-2.5 py-1.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#2a4a3a] min-h-[36px] transition-colors"
            onclick="openActionModal({m['id']},'done')">Mark Done</button>
    <button class="bg-[#3d1a1a] text-[#f85149] border border-[#5a2a2a] rounded-lg px-2.5 py-1.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#4a2a2a] min-h-[36px] transition-colors"
            onclick="openActionModal({m['id']},'cancelled')">Reject</button>
  </div>"""

    project_html = ""
    if m["project"]:
        pq = build_qs(project=m["project"])
        project_html = f"""
            <a class="bg-[#1a2a3d] text-[#58a6ff] px-1.5 py-0.5 rounded text-[11px] no-underline hover:underline cursor-pointer"
               hx-get="/ui/tasks?{pq}" hx-target="#tab-content" hx-push-url="true">{esc(m['project'])}</a>"""

    desc_html = ""
    if m.get("description"):
        desc_html = f'<div class="text-sm whitespace-pre-wrap break-words mt-2 text-[#8b949e] line-clamp-3">{esc(m["description"])}</div>'

    return f"""<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-4 shadow-sm
                    hover:border-[#30404d] hover:shadow-md transition-all flex flex-col" id="task-{m['id']}">
  <div class="flex items-center gap-2 mb-2 flex-wrap">
    <span class="text-[#8b949e] text-xs font-mono cursor-pointer hover:text-[#58a6ff]"
          title="Click to copy #{m['id']}" onclick="navigator.clipboard.writeText('#{m['id']}')">#{m['id']}</span>
    {priority_label(m['priority'])}
    {status_badge(m['status'])}
  </div>
  <div class="text-[15px] font-semibold mb-1 line-clamp-2">{esc(m['title'])}</div>
  {desc_html}
  <div class="mt-auto pt-3 flex items-center justify-between text-xs text-[#8b949e]">
    <div class="flex items-center gap-2 min-w-0">
      <span class="text-[#bc8cff] font-semibold shrink-0">{esc(m['username'])}</span>
      {project_html}
    </div>
    {time_tag(m['updated_at'])}
  </div>
  {action_btns}
</div>"""


def render_task_compact(row) -> str:
    """Abbreviated task row for dashboard widget."""
    m = row._mapping
    project_html = ""
    if m["project"]:
        project_html = f'<span class="text-[#8b949e]">{esc(m["project"])}</span>'
    return f"""<div class="flex items-center gap-3 py-2 border-b border-[#1e2733] last:border-b-0">
  <span class="text-[#8b949e] text-xs font-mono shrink-0">#{m['id']}</span>
  {priority_label(m['priority'])}
  {status_badge(m['status'])}
  <span class="text-sm truncate flex-1 min-w-0">{esc(m['title'])}</span>
  <span class="text-[#bc8cff] text-xs font-semibold shrink-0">{esc(m['username'])}</span>
  {project_html}
</div>"""


def render_journal_card(row) -> str:
    m = row._mapping
    project_html = ""
    if m["project"]:
        pq = build_qs(project=m["project"])
        project_html = f"""
            <a class="bg-[#1a2a3d] text-[#58a6ff] px-1.5 py-0.5 rounded text-[11px] no-underline hover:underline cursor-pointer"
               hx-get="/ui/journal?{pq}" hx-target="#tab-content" hx-push-url="true">{esc(m['project'])}</a>"""

    return f"""<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-4 shadow-sm
                    flex flex-col hover:border-[#30404d] hover:shadow-md transition-all">
  <div class="flex items-center gap-2 mb-2 text-xs text-[#8b949e] flex-wrap">
    <span class="font-mono">#{m['id']}</span>
    <span class="text-[#bc8cff] font-semibold text-[13px]">{esc(m['username'])}</span>
    {project_html}
    <span class="ml-auto shrink-0">{time_tag(m['created_at'])}</span>
  </div>
  <div class="text-sm whitespace-pre-wrap break-words line-clamp-6 flex-1">{esc(m['content'])}</div>
</div>"""


def render_journal_compact(row) -> str:
    """Abbreviated journal row for dashboard widget."""
    m = row._mapping
    project_html = ""
    if m["project"]:
        project_html = f'<span class="text-[#8b949e]">{esc(m["project"])}</span>'
    # Truncate content to first line
    content = str(m["content"] or "")
    first_line = content.split("\n")[0][:120]
    if len(first_line) < len(content):
        first_line += "..."
    return f"""<div class="flex items-center gap-3 py-2 border-b border-[#1e2733] last:border-b-0">
  <span class="text-[#8b949e] text-xs font-mono shrink-0">#{m['id']}</span>
  <span class="text-[#bc8cff] text-xs font-semibold shrink-0">{esc(m['username'])}</span>
  {project_html}
  <span class="text-sm text-[#8b949e] truncate flex-1 min-w-0">{esc(first_line)}</span>
  <span class="text-xs text-[#8b949e] shrink-0" title="{esc(m['created_at'])}">{time_ago(m['created_at'])}</span>
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
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle">
    <a class="font-semibold text-[#58a6ff] text-[13px] no-underline hover:underline"
       href="https://github.com/agentine/{quote(name)}" target="_blank">{esc(name)}</a>
    {desc_html}
  </td>
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle">{lang_tag(m['language'])}</td>
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle">{project_status_badge(m['status'])}</td>
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle">{tc_html}</td>
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle">{jc_html}</td>
  <td class="px-2.5 py-2 border-b border-[#1e2733] align-middle whitespace-nowrap">{time_tag(m['updated_at'])}</td>
</tr>"""


def render_key_row(row) -> str:
    m = row._mapping
    return f"""<div class="flex items-center gap-3 px-4 py-2.5 border-b border-[#1e2733] last:border-b-0">
  <span class="font-semibold text-sm min-w-[120px]">{esc(m['name'])}</span>
  <span class="font-mono text-[13px] text-[#8b949e] bg-[#0d1117] px-2 py-0.5 rounded">{esc(m['key'])}</span>
  <span class="ml-auto">{time_tag(m['created_at'])}</span>
  <button class="bg-[#3d1a1a] text-[#f85149] border border-[#5a2a2a] rounded-lg px-2.5 py-1.5 text-xs font-semibold cursor-pointer whitespace-nowrap hover:bg-[#4a2a2a] min-h-[44px] transition-colors"
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
  <button class="bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] px-4 py-2 rounded-md text-[13px] cursor-pointer min-h-[36px] hover:bg-[#161b22] transition-colors {prev_disabled}"
          hx-get="{path}?{prev_qs}" hx-target="#tab-content" hx-push-url="true">{prev_label}</button>
  <span class="text-[13px] text-[#8b949e]">{page} / {pages}</span>
  <button class="bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] px-4 py-2 rounded-md text-[13px] cursor-pointer min-h-[36px] hover:bg-[#161b22] transition-colors {next_disabled}"
          hx-get="{path}?{next_qs}" hx-target="#tab-content" hx-push-url="true">{next_label}</button>
</div>"""


# ── Filter Bar Renderers ─────────────────────────────────────────────

INPUT_CLS = (
    "bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] px-3 py-2 rounded-md text-[13px]"
    " placeholder:text-[#484f58] min-h-[36px]"
    " focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff]"
    " transition-colors"
)
SELECT_CLS = (
    "bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] pl-3 pr-8 py-2 rounded-md text-[13px]"
    " min-h-[36px] cursor-pointer appearance-none"
    " focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff]"
    " transition-colors"
)


def _search_input(name: str, value: str, placeholder: str, path: str) -> str:
    active_border = " !border-[#58a6ff]" if value else ""
    return f"""<div class="relative w-full sm:w-[220px]">
  <span class="absolute left-2.5 top-1/2 -translate-y-1/2 text-[#484f58] pointer-events-none">{ICONS["search"]}</span>
  <input name="{name}" value="{esc(value)}" placeholder="{placeholder}" autocomplete="off"
         class="{INPUT_CLS} w-full !pl-8{active_border}"
         hx-get="{path}" hx-target="#tab-content" hx-trigger="input changed delay:300ms"
         hx-include="closest form" hx-push-url="true" />
</div>"""


def _select(name: str, value: str, options: list[tuple[str, str]], path: str) -> str:
    opts = []
    for val, label in options:
        sel = " selected" if val == value else ""
        opts.append(f'<option value="{esc(val)}"{sel}>{esc(label)}</option>')
    active_border = " !border-[#58a6ff]" if value else ""
    return f"""<div class="relative inline-block">
  <select name="{name}" class="{SELECT_CLS}{active_border}"
       hx-get="{path}" hx-target="#tab-content" hx-trigger="change"
       hx-include="closest form" hx-push-url="true">
  {"".join(opts)}
  </select>
  <span class="absolute right-2 top-1/2 -translate-y-1/2 text-[#484f58] pointer-events-none">{ICONS["chevron-down"]}</span>
</div>"""


def _text_input(
    name: str, value: str, placeholder: str, path: str, datalist: str = ""
) -> str:
    dl = f' list="{datalist}"' if datalist else ""
    extra = ' data-1p-ignore data-lpignore="true" data-form-type="other"' if name in ("username",) else ""
    active_border = " !border-[#58a6ff]" if value else ""
    return f"""<input name="{name}" value="{esc(value)}" placeholder="{placeholder}" autocomplete="off"
       class="{INPUT_CLS}{active_border}"{dl}{extra}
       hx-get="{path}" hx-target="#tab-content" hx-trigger="input changed delay:300ms"
       hx-include="closest form" hx-push-url="true" />"""


def _clear_filters_btn(path: str, has_filters: bool) -> str:
    if not has_filters:
        return ""
    return f"""<a class="inline-flex items-center gap-1 text-xs text-[#8b949e] hover:text-[#e6edf3] cursor-pointer transition-colors px-2 py-1.5 rounded-md hover:bg-[#161b22] min-h-[36px] no-underline"
       hx-get="{path}" hx-target="#tab-content" hx-push-url="true">
  {ICONS["x"]} Clear filters
</a>"""


# ── Tab Content Renderers ─────────────────────────────────────────────


def render_dashboard_tab(db: Session) -> str:
    """Dashboard home view with summary widgets."""
    # Recent active tasks
    recent_tasks = db.execute(
        select(tasks)
        .where(tasks.c.status.in_(["pending", "in_progress", "blocked"]))
        .order_by(tasks.c.priority.desc(), tasks.c.updated_at.desc())
        .limit(8)
    ).fetchall()

    # Recent journal
    recent_journal = db.execute(
        select(journal)
        .order_by(journal.c.created_at.desc())
        .limit(5)
    ).fetchall()

    # Active agents
    active_agents = db.execute(
        select(agents).order_by(agents.c.updated_at.desc())
    ).fetchall()

    # Human action needed
    human_tasks = db.execute(
        select(tasks)
        .where(tasks.c.username == "human")
        .where(tasks.c.status.in_(["pending", "in_progress", "blocked"]))
        .order_by(tasks.c.priority.desc())
    ).fetchall()

    # Human alert banner
    human_banner = ""
    if human_tasks:
        count = len(human_tasks)
        hq = build_qs(username="human", status="pending")
        human_banner = f"""<div class="lg:col-span-2 bg-[#2a2210] border border-[#d29922] rounded-xl px-5 py-4 flex items-center gap-4 shadow-md cursor-pointer hover:bg-[#332b14] transition-colors"
     hx-get="/ui/tasks?{hq}" hx-target="#tab-content" hx-push-url="true">
  <span class="text-[#d29922]">{ICONS["alert"]}</span>
  <div>
    <div class="font-semibold text-[#d29922]">{count} task{"s" if count != 1 else ""} need{"" if count != 1 else "s"} human action</div>
    <div class="text-xs text-[#8b949e] mt-0.5">Click to view and resolve pending human tasks</div>
  </div>
</div>"""

    # Tasks widget
    if recent_tasks:
        task_items = "".join(render_task_compact(r) for r in recent_tasks)
    else:
        task_items = '<div class="text-sm text-[#8b949e] py-4 text-center">No active tasks</div>'

    tasks_widget = f"""<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 shadow-md">
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-sm font-semibold uppercase tracking-wider text-[#8b949e]">Active Tasks</h2>
    <a hx-get="/ui/tasks" hx-target="#tab-content" hx-push-url="true"
       class="text-xs text-[#58a6ff] cursor-pointer hover:underline">View all</a>
  </div>
  {task_items}
</div>"""

    # Agents widget
    if active_agents:
        agent_items = []
        for row in active_agents:
            m = row._mapping
            dot_cls = "bg-[#3fb950] shadow-[0_0_4px_#3fb950]" if m["status"] == "running" else "bg-[#8b949e]"
            proj = f'<div class="text-[11px] text-[#8b949e] truncate">{esc(m["project"])}</div>' if m["project"] else '<div class="text-[11px] text-[#8b949e]">no project</div>'
            agent_items.append(
                f'<div class="flex items-center gap-3 py-2.5 border-b border-[#1e2733] last:border-b-0">'
                f'<span class="w-2.5 h-2.5 rounded-full {dot_cls} shrink-0"></span>'
                f'<div class="flex-1 min-w-0">'
                f'<div class="text-sm font-medium">{esc(m["username"])}</div>'
                f'{proj}</div>'
                f'<div class="text-xs text-[#8b949e] shrink-0">{time_ago(m["updated_at"])}</div>'
                f'</div>'
            )
        agents_html = "".join(agent_items)
    else:
        agents_html = '<div class="text-sm text-[#8b949e] py-4 text-center">No agents registered</div>'

    agents_widget = f"""<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 shadow-md">
  <h2 class="text-sm font-semibold uppercase tracking-wider text-[#8b949e] mb-4">Agents</h2>
  {agents_html}
</div>"""

    # Journal widget
    if recent_journal:
        journal_items = "".join(render_journal_compact(r) for r in recent_journal)
    else:
        journal_items = '<div class="text-sm text-[#8b949e] py-4 text-center">No journal entries</div>'

    journal_widget = f"""<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 shadow-md lg:col-span-2">
  <div class="flex justify-between items-center mb-4">
    <h2 class="text-sm font-semibold uppercase tracking-wider text-[#8b949e]">Recent Journal</h2>
    <a hx-get="/ui/journal" hx-target="#tab-content" hx-push-url="true"
       class="text-xs text-[#58a6ff] cursor-pointer hover:underline">View all</a>
  </div>
  {journal_items}
</div>"""

    return f"""<div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
  {human_banner}
  {tasks_widget}
  {agents_widget}
  {journal_widget}
</div>"""


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

    has_filters = bool(search or status or language)
    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search projects...", path)}
  {_select("status", status, status_options, path)}
  {_select("language", language, lang_options, path)}
  {_clear_filters_btn(path, has_filters)}
</form>"""

    if rows:
        table_rows = "".join(
            render_project_row(r, task_counts_map.get(r._mapping["name"], {}), journal_counts_map.get(r._mapping["name"], 0))
            for r in rows
        )
        list_html = f"""<div class="overflow-x-auto">
  <table class="w-full min-w-[600px] border-collapse text-[13px]">
    <thead><tr>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Project</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Lang</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Status</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Tasks</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Journal</th>
      <th class="text-left px-2.5 py-2 border-b-2 border-[#1e2733] text-[#8b949e] text-[11px] uppercase tracking-wider font-semibold whitespace-nowrap">Updated</th>
    </tr></thead>
    <tbody>{table_rows}</tbody>
  </table>
</div>"""
    else:
        list_html = f'<div class="flex flex-col items-center justify-center py-16 text-[#8b949e]">{ICONS["inbox"]}<div class="mt-3 text-sm font-medium">No projects found</div><div class="text-xs mt-1">Try adjusting your filters</div></div>'

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
            items_html = f'<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">{render_task_card(row)}</div>'
            total = 1
        else:
            items_html = f'<div class="flex flex-col items-center justify-center py-16 text-[#8b949e]">{ICONS["inbox"]}<div class="mt-3 text-sm font-medium">Task {esc(search)} not found</div></div>'
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
            cards = "".join(render_task_card(r) for r in rows)
            items_html = f'<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">{cards}</div>'
        else:
            items_html = f'<div class="flex flex-col items-center justify-center py-16 text-[#8b949e]">{ICONS["inbox"]}<div class="mt-3 text-sm font-medium">No tasks</div><div class="text-xs mt-1">Create a task or adjust your filters</div></div>'

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

    has_filters = bool(search or username or project or status or priority)
    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search or #id...", path)}
  {_text_input("username", username, "agent", path, "dl-users")}
  {_text_input("project", project, "project", path, "dl-projects")}
  {_select("status", status, status_options, path)}
  {_select("priority", priority, priority_options, path)}
  {_select("sort", sort, sort_options, path)}
  <button type="button" class="bg-[#e6edf3] text-[#0d1117] border-none rounded-md px-3.5 py-2 text-[13px] font-semibold cursor-pointer hover:bg-[#cdd5de] min-h-[36px] transition-colors"
          onclick="openNewTaskModal()">+ New Task</button>
  {_clear_filters_btn(path, has_filters)}
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
        cards = "".join(render_journal_card(r) for r in rows)
        items_html = f'<div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">{cards}</div>'
    else:
        items_html = f'<div class="flex flex-col items-center justify-center py-16 text-[#8b949e]">{ICONS["inbox"]}<div class="mt-3 text-sm font-medium">No journal entries</div><div class="text-xs mt-1">Entries will appear as agents log their activity</div></div>'

    path = "/ui/journal"
    sort_options = [("desc", "Newest first"), ("asc", "Oldest first")]

    dl_users = "".join(f'<option value="{esc(u)}">' for u in usernames)
    dl_projects = "".join(f'<option value="{esc(p)}">' for p in projects_list)

    has_filters = bool(search or username or project)
    filters_html = f"""<form class="flex gap-2 mb-4 flex-wrap items-center">
  {_search_input("search", search, "search content...", path)}
  {_text_input("username", username, "agent", path, "dl-users")}
  {_text_input("project", project, "project", path, "dl-projects")}
  {_select("sort", sort, sort_options, path)}
  {_clear_filters_btn(path, has_filters)}
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
  <button type="button" class="bg-[#e6edf3] text-[#0d1117] border-none rounded-md px-3.5 py-2 text-[13px] font-semibold cursor-pointer hover:bg-[#cdd5de] min-h-[36px] transition-colors"
          onclick="openNewKeyModal()">+ New Key</button>
</div>"""

    if not authed:
        return f"""{btn}
<div id="key-banner"></div>
<div class="text-center text-[#8b949e] py-10 text-sm">Enter a valid API key in the sidebar to manage keys.</div>"""

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
        items_html = '<div class="bg-[#161b22] border border-[#1e2733] rounded-xl overflow-hidden shadow-sm">'
        items_html += "".join(render_key_row(MaskedRow(r)) for r in rows)
        items_html += "</div>"
    else:
        items_html = f'<div class="flex flex-col items-center justify-center py-16 text-[#8b949e]">{ICONS["inbox"]}<div class="mt-3 text-sm font-medium">No API keys</div><div class="text-xs mt-1">Auth is currently disabled (open access)</div></div>'

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
    agent_count = db.execute(select(func.count()).select_from(agents)).scalar() or 0
    running_agents = db.execute(
        select(func.count()).select_from(agents).where(agents.c.status == "running")
    ).scalar() or 0
    journal_count = db.execute(select(func.count()).select_from(journal)).scalar() or 0

    pending = task_counts.get("pending", 0)
    in_progress = task_counts.get("in_progress", 0)
    blocked = task_counts.get("blocked", 0)
    done = task_counts.get("done", 0)
    cancelled = task_counts.get("cancelled", 0)

    done_pct = int(done / total_tasks * 100) if total_tasks > 0 else 0
    agent_pct = int(running_agents / agent_count * 100) if agent_count > 0 else 0

    return f"""<div class="flex gap-4 flex-wrap">
  <div class="bg-[#161b22] border border-[#1e2733] rounded-xl px-5 py-4 flex flex-col min-w-[140px] shadow-md flex-1 cursor-pointer hover:border-[#30404d] hover:shadow-lg transition-all"
       hx-get="/ui/tasks" hx-target="#tab-content" hx-push-url="true">
    <span class="text-[28px] font-bold leading-tight">{total_tasks}</span>
    <span class="text-xs text-[#8b949e] uppercase tracking-wider font-medium mt-0.5">Total Tasks</span>
    <div class="mt-3 w-full bg-[#0d1117] rounded-full h-1.5 overflow-hidden">
      <div class="h-full bg-[#58a6ff] rounded-full transition-all" style="width:{done_pct}%"></div>
    </div>
    <div class="flex gap-3 mt-2 text-[11px] text-[#8b949e] flex-wrap">
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-[#8b949e] inline-block"></span>{pending}p</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-[#3fb950] inline-block"></span>{in_progress}a</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-[#d29922] inline-block"></span>{blocked}b</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-[#58a6ff] inline-block"></span>{done}d</span>
      <span class="flex items-center gap-1"><span class="w-2 h-2 rounded-full bg-[#f85149] inline-block"></span>{cancelled}x</span>
    </div>
  </div>
  <div class="bg-[#161b22] border border-[#1e2733] rounded-xl px-5 py-4 flex flex-col min-w-[140px] shadow-md cursor-pointer hover:border-[#30404d] hover:shadow-lg transition-all"
       hx-get="/ui/dashboard" hx-target="#tab-content" hx-push-url="true">
    <span class="text-[28px] font-bold leading-tight">{running_agents} <span class="text-base font-normal text-[#8b949e]">/ {agent_count}</span></span>
    <span class="text-xs text-[#8b949e] uppercase tracking-wider font-medium mt-0.5">Agents Online</span>
    <div class="mt-3 w-full bg-[#0d1117] rounded-full h-1.5 overflow-hidden">
      <div class="h-full bg-[#3fb950] rounded-full transition-all" style="width:{agent_pct}%"></div>
    </div>
  </div>
  <div class="bg-[#161b22] border border-[#1e2733] rounded-xl px-5 py-4 flex flex-col min-w-[140px] shadow-md cursor-pointer hover:border-[#30404d] hover:shadow-lg transition-all"
       hx-get="/ui/journal" hx-target="#tab-content" hx-push-url="true">
    <span class="text-[28px] font-bold leading-tight">{journal_count}</span>
    <span class="text-xs text-[#8b949e] uppercase tracking-wider font-medium mt-0.5">Journal Entries</span>
  </div>
</div>"""


def render_presence_html(db: Session) -> str:
    rows = db.execute(
        select(agents).order_by(agents.c.updated_at.desc())
    ).fetchall()

    if not rows:
        return '<div class="text-xs text-[#8b949e] italic py-1">no agents online</div>'

    items = []
    for row in rows:
        m = row._mapping
        dot_cls = "bg-[#3fb950] shadow-[0_0_4px_#3fb950]" if m["status"] == "running" else "bg-[#8b949e]"
        project_html = ""
        if m["project"]:
            project_html = f'<div class="text-[11px] text-[#8b949e] truncate">{esc(m["project"])}</div>'
        items.append(
            f'<div class="flex items-center gap-2 py-1.5">'
            f'<span class="w-2 h-2 rounded-full shrink-0 {dot_cls}"></span>'
            f'<div class="min-w-0 flex-1">'
            f'<div class="text-xs font-medium truncate">{esc(m["username"])}</div>'
            f'{project_html}'
            f'</div>'
            f'</div>'
        )
    return "".join(items)


# ── Sidebar Navigation ───────────────────────────────────────────────


def render_sidebar_nav(active: str) -> str:
    tabs_def = [
        ("dashboard", "Dashboard", ICONS["dashboard"]),
        ("projects", "Projects", ICONS["folder"]),
        ("tasks", "Tasks", ICONS["tasks"]),
        ("journal", "Journal", ICONS["journal"]),
        ("keys", "Keys", ICONS["key"]),
    ]
    items = []
    for tab_id, label, icon in tabs_def:
        if tab_id == active:
            active_cls = "bg-[#1f2937] text-[#e6edf3] border-l-2 border-l-[#58a6ff]"
        else:
            active_cls = "text-[#8b949e] hover:text-[#e6edf3] hover:bg-[#161b22] border-l-2 border-l-transparent"
        items.append(
            f'<a class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium {active_cls}'
            f' transition-colors min-h-[44px] cursor-pointer no-underline"'
            f' hx-get="/ui/{tab_id}" hx-target="#tab-content" hx-push-url="true">'
            f'{icon}<span>{label}</span></a>'
        )
    return "\n    ".join(items)


def render_sidebar_nav_oob(active: str) -> str:
    return f'<nav id="sidebar-nav" class="flex-1 px-3 py-4 space-y-1 overflow-y-auto" hx-swap-oob="innerHTML">{render_sidebar_nav(active)}</nav>'


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

// Sidebar toggle (mobile)
function toggleSidebar() {
  var sb = document.getElementById('sidebar');
  var ov = document.getElementById('sidebar-overlay');
  if (sb.classList.contains('-translate-x-full')) {
    sb.classList.remove('-translate-x-full');
    ov.classList.remove('hidden');
  } else {
    sb.classList.add('-translate-x-full');
    ov.classList.add('hidden');
  }
}
// Restore focus to the active input after htmx swaps (prevents search losing focus)
document.addEventListener('htmx:beforeSwap', function(evt) {
  var ae = document.activeElement;
  if (ae && ae.tagName === 'INPUT' && ae.name && evt.detail.target.id === 'tab-content') {
    evt.detail._restoreFocus = { name: ae.name, pos: ae.selectionStart };
  }
});
document.addEventListener('htmx:afterSwap', function(evt) {
  var rf = evt.detail._restoreFocus;
  if (rf) {
    var el = document.querySelector('#tab-content [name="' + rf.name + '"]');
    if (el) { el.focus(); if (rf.pos != null) try { el.setSelectionRange(rf.pos, rf.pos); } catch(e) {} }
  }
});
// Auto-close sidebar on navigation (mobile)
document.addEventListener('htmx:afterSwap', function() {
  if (window.innerWidth < 1024) {
    var sb = document.getElementById('sidebar');
    var ov = document.getElementById('sidebar-overlay');
    if (sb && !sb.classList.contains('-translate-x-full')) {
      sb.classList.add('-translate-x-full');
      if (ov) ov.classList.add('hidden');
    }
  }
});

// Task action modal
var actionTaskId = null, actionStatus = null;
function openActionModal(taskId, status) {
  actionTaskId = taskId;
  actionStatus = status;
  var isDone = status === 'done';
  var overlay = document.createElement('div');
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50 modal-enter';
  overlay.id = 'action-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">' + (isDone ? 'Mark Task Done' : 'Reject Task') + '</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">' + (isDone ? 'Provide a brief summary of what was completed.' : 'Provide a reason for rejecting this task.') + '</div>' +
    '<textarea id="action-summary" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] font-[inherit] resize-y min-h-[80px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors" placeholder="' + (isDone ? 'Summary of work done...' : 'Reason for rejection...') + '"></textarea>' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#1e2733] text-[#e6edf3] px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border border-[#30363d] min-h-[36px] hover:bg-[#30363d] transition-colors" onclick="closeActionModal()">Cancel</button>' +
    '<button class="' + (isDone ? 'bg-[#3fb950] text-black' : 'bg-[#f85149] text-white') + ' px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border-none min-h-[36px]" id="action-submit" onclick="submitAction()">' + (isDone ? 'Complete' : 'Reject') + '</button>' +
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
    var res = await fetch('/api/tasks/' + actionTaskId, {
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
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50 modal-enter';
  overlay.id = 'new-task-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">New Task</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">Assign a task to an agent or team member.</div>' +
    '<label class="block text-xs text-[#8b949e] mb-1">Assign to</label>' +
    '<input id="nt-user" list="dl-users" placeholder="agent" autocomplete="off" data-1p-ignore data-lpignore="true" data-form-type="other" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] mb-2 min-h-[36px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors" />' +
    '<label class="block text-xs text-[#8b949e] mb-1">Title</label>' +
    '<input id="nt-title" placeholder="Task title" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] mb-2 min-h-[36px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors" />' +
    '<div class="flex gap-2.5">' +
    '<div class="flex-1"><label class="block text-xs text-[#8b949e] mb-1">Priority</label>' +
    '<select id="nt-priority" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] min-h-[36px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors">' +
    '<option value="1">P1 (lowest)</option><option value="2">P2</option><option value="3" selected>P3</option><option value="4">P4</option><option value="5">P5 (highest)</option></select></div>' +
    '<div class="flex-1"><label class="block text-xs text-[#8b949e] mb-1">Project</label>' +
    '<input id="nt-project" list="dl-projects" placeholder="optional" autocomplete="off" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] min-h-[36px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors" /></div></div>' +
    '<label class="block text-xs text-[#8b949e] mb-1 mt-2.5">Description</label>' +
    '<textarea id="nt-desc" placeholder="Describe what needs to be done..." class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-lg p-2 text-[13px] font-[inherit] resize-y min-h-[80px]"></textarea>' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#1e2733] text-[#e6edf3] px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border border-[#30363d] min-h-[36px] hover:bg-[#30363d] transition-colors" onclick="closeNewTaskModal()">Cancel</button>' +
    '<button class="bg-[#3fb950] text-black px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border-none min-h-[36px]" id="nt-submit" onclick="submitNewTask()">Create Task</button>' +
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
    var res = await fetch('/api/tasks', {
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
  overlay.className = 'fixed inset-0 bg-black/60 flex items-center justify-center z-50 modal-enter';
  overlay.id = 'new-key-modal';
  overlay.innerHTML = '<div class="bg-[#161b22] border border-[#1e2733] rounded-xl p-5 w-[420px] max-w-[90vw]">' +
    '<h2 class="text-base font-semibold mb-1">Create API Key</h2>' +
    '<div class="text-[13px] text-[#8b949e] mb-3">Give this key a name to identify what system or agent uses it.</div>' +
    '<label class="block text-xs text-[#8b949e] mb-1">Name</label>' +
    '<input id="nk-name" placeholder="e.g. ci-pipeline, agent-alpha, matt" autocomplete="off" class="w-full bg-[#0d1117] border border-[#1e2733] text-[#e6edf3] rounded-md p-2.5 text-[13px] min-h-[36px] focus:outline-none focus:ring-2 focus:ring-[#58a6ff]/40 focus:border-[#58a6ff] transition-colors" />' +
    '<div class="flex gap-2 justify-end mt-3">' +
    '<button class="bg-[#1e2733] text-[#e6edf3] px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border border-[#30363d] min-h-[36px] hover:bg-[#30363d] transition-colors" onclick="closeNewKeyModal()">Cancel</button>' +
    '<button class="bg-[#3fb950] text-black px-4 py-2 rounded-md text-[13px] font-medium cursor-pointer border-none min-h-[36px]" id="nk-submit" onclick="submitNewKey()">Create</button>' +
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
    var res = await fetch('/api/keys', {
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
      banner.innerHTML = '<div class="bg-[#1a3a2a] border border-[#2a5a3a] rounded-xl px-4 py-3 mb-3">' +
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
    var res = await fetch('/api/keys/' + id, {
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


SHELL_CSS = """
  #tab-content { transition: opacity 150ms ease-in-out; }
  .htmx-swapping > #tab-content { opacity: 0; }
  .modal-enter { animation: fadeIn 150ms ease-out; }
  @keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
  .modal-enter > div { animation: slideUp 150ms ease-out; }
  @keyframes slideUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  .line-clamp-2 { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
  .line-clamp-3 { display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
  .line-clamp-6 { display: -webkit-box; -webkit-line-clamp: 6; -webkit-box-orient: vertical; overflow: hidden; }

  /* Timestamp tooltips */
  .timestamp { position: relative; }
  .timestamp:hover::after {
    content: attr(data-ts);
    position: absolute;
    bottom: calc(100% + 6px);
    left: 50%;
    transform: translateX(-50%);
    background: #1e2733;
    border: 1px solid #30363d;
    color: #e6edf3;
    font-size: 11px;
    font-family: monospace;
    padding: 4px 8px;
    border-radius: 6px;
    white-space: nowrap;
    z-index: 50;
    pointer-events: none;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
  }
  .timestamp:hover::before {
    content: '';
    position: absolute;
    bottom: calc(100% + 2px);
    left: 50%;
    transform: translateX(-50%);
    border: 4px solid transparent;
    border-top-color: #1e2733;
    z-index: 50;
    pointer-events: none;
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
<style>{SHELL_CSS}</style>
</head>
<body class="bg-[#111821] text-[#e6edf3] font-[-apple-system,BlinkMacSystemFont,'Segoe_UI',Helvetica,Arial,sans-serif] leading-relaxed">

<!-- Sidebar -->
<aside id="sidebar" class="fixed top-0 left-0 h-screen w-60 bg-[#0f1318] border-r border-[#1e2733]
                           flex flex-col z-40 transition-transform duration-200
                           -translate-x-full lg:translate-x-0">
  <div class="px-4 py-5 border-b border-[#1e2733]">
    <div class="flex items-center justify-between">
      <h1 class="text-base font-semibold">Agent Comms</h1>
      <a href="https://github.com/agentine" target="_blank"
         class="text-[#8b949e] hover:text-[#e6edf3] transition-colors">{ICONS["github"]}</a>
    </div>
  </div>

  <nav id="sidebar-nav" class="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
    {render_sidebar_nav(active_tab)}
  </nav>

  <div class="px-3 py-3 border-t border-[#1e2733]">
    <div class="text-[11px] text-[#8b949e] uppercase tracking-wider font-semibold mb-2">Agents</div>
    <div id="presence-bar" class="space-y-0 max-h-[180px] overflow-y-auto"
         hx-get="/ui/partials/presence" hx-trigger="every 5s" hx-swap="innerHTML">
      {presence_html}
    </div>
  </div>

  <div class="px-3 py-3 border-t border-[#1e2733]">
    <div class="flex gap-1.5 items-center">
      <input id="api-key" type="password" placeholder="API key" autocomplete="off"
             class="bg-[#161b22] border border-[#1e2733] text-[#e6edf3] px-2 py-1.5 rounded-lg text-xs w-full placeholder:text-[#8b949e]" />
      <button onclick="saveApiKey()"
              class="bg-[#161b22] border border-[#1e2733] text-[#e6edf3] px-2 py-1.5 rounded-lg text-xs cursor-pointer shrink-0 hover:bg-[#1f2937] transition-colors">Save</button>
    </div>
    <span id="api-key-status" class="text-[11px] text-[#8b949e]"></span>
  </div>
</aside>

<!-- Mobile hamburger -->
<button id="sidebar-toggle"
        class="lg:hidden fixed top-4 left-4 z-50 bg-[#161b22] border border-[#1e2733] rounded-lg p-2.5 min-w-[44px] min-h-[44px] text-[#8b949e] hover:text-[#e6edf3] transition-colors"
        onclick="toggleSidebar()">
  {ICONS["menu"]}
</button>

<!-- Overlay for mobile sidebar -->
<div id="sidebar-overlay" class="fixed inset-0 bg-black/50 z-30 hidden" onclick="toggleSidebar()"></div>

<!-- Main content -->
<main class="lg:ml-60 min-h-screen transition-[margin] duration-200">
  <div class="px-4 sm:px-6 py-6 max-w-[1600px]">
    <div id="stats-bar" class="mb-6" hx-get="/ui/partials/stats" hx-trigger="every 5s" hx-swap="innerHTML">
      {stats_html}
    </div>

    <div id="tab-content">
      {content}
    </div>
  </div>
</main>

<script>{CLIENT_JS}</script>
</body>
</html>"""


LANDING_PAGE = f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentine</title>
<script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-[#111821] text-[#e6edf3] font-[-apple-system,BlinkMacSystemFont,'Segoe_UI',Helvetica,Arial,sans-serif] min-h-screen flex items-center justify-center">
<div class="max-w-2xl mx-auto px-6 py-16 text-center">
  <h1 class="text-4xl font-bold mb-3">Agentine</h1>
  <p class="text-[#8b949e] text-lg mb-10 max-w-md mx-auto">
    Agent communication platform &mdash; coordinate tasks, share journals, and monitor agent activity.
  </p>
  <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
    <a href="/ui"
       class="bg-[#161b22] border border-[#1e2733] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors shadow-lg min-h-[44px]">
      <div class="text-2xl mb-2 flex justify-center text-[#58a6ff]">{ICONS["chart"]}</div>
      <div class="font-semibold mb-1">Dashboard</div>
      <div class="text-sm text-[#8b949e]">View projects, tasks, and agent activity</div>
    </a>
    <a href="/api/docs"
       class="bg-[#161b22] border border-[#1e2733] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors shadow-lg min-h-[44px]">
      <div class="text-2xl mb-2 flex justify-center text-[#58a6ff]">{ICONS["book"]}</div>
      <div class="font-semibold mb-1">API Docs</div>
      <div class="text-sm text-[#8b949e]">Interactive API documentation</div>
    </a>
    <a href="https://github.com/agentine" target="_blank"
       class="bg-[#161b22] border border-[#1e2733] rounded-xl p-6 no-underline text-[#e6edf3] hover:border-[#58a6ff] transition-colors shadow-lg min-h-[44px]">
      <div class="text-2xl mb-2 flex justify-center text-[#8b949e]">
        <svg class="w-7 h-7" fill="currentColor" viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"></path></svg>
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
    return RedirectResponse(url="/ui/dashboard", status_code=302)


@router.get("/ui/dashboard", response_class=HTMLResponse)
def ui_dashboard_page(
    request: Request,
    db: Session = Depends(get_db),
):
    content = render_dashboard_tab(db)
    if is_htmx(request):
        return HTMLResponse(content + render_sidebar_nav_oob("dashboard"))
    stats_html = render_stats_html(db)
    presence_html = render_presence_html(db)
    return HTMLResponse(render_shell("dashboard", content, stats_html, presence_html))


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
        return HTMLResponse(content + render_sidebar_nav_oob("projects"))
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
        return HTMLResponse(content + render_sidebar_nav_oob("tasks"))
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
        return HTMLResponse(content + render_sidebar_nav_oob("journal"))
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
        return HTMLResponse(content + render_sidebar_nav_oob("keys"))
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
