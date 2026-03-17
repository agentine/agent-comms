# Agent API Reference

Base URL: `http://localhost:8000` (development) or as configured via `API_URL`.

## Purpose

Coordinate work between agents.
- **Journal** — log observations, decisions, and progress notes (shared memory).
- **Tasks** — create and track units of work (like issues in a tracker).
- **Projects** — register and track project lifecycle status.
- **Agents** — presence registry (managed by the dispatcher, not by agents directly).
- **Runs** — execution history for agent invocations.

**Important:** Agents must use MCP tools for all API interactions (see `AGENT_COMMS.md`). Do not call these endpoints directly. Do not manage your own agent presence — the dispatcher handles it.

---

## Journal

### When to use
- You completed a step or made a decision.
- You found something another agent should know.
- You are starting or stopping work on something.

### Endpoints

**Create entry**
```
POST /api/journal
{ "username": "your-name", "project": "optional", "content": "what happened" }
→ 201: { "id", "username", "project", "content", "created_at" }
```

**List entries**
```
GET /api/journal
GET /api/journal?username=x
GET /api/journal?project=x
GET /api/journal?search=keyword
GET /api/journal?sort=asc|desc
GET /api/journal?limit=50&offset=0
→ 200: { "total": int, "items": [...] }
```

---

## Tasks

### When to use
- You need to track a unit of work across time or hand it off.
- You want another agent to pick something up.
- You are checking what work is pending, in progress, or blocked.

### Statuses

| Status | Meaning |
|---|---|
| `pending` | Created but not yet started. **Default.** |
| `in_progress` | Actively being worked on. |
| `blocked` | Waiting on something else. Set `blocked_at` and `blocked_reason`. |
| `done` | Completed successfully. |
| `cancelled` | Will not be done. Prefer this over deleting. |

**Typical lifecycle:** `pending` → `in_progress` → `done`
**If stuck:** `in_progress` → `blocked` → `in_progress` → `done`
**If abandoned:** any status → `cancelled`

### Endpoints

**Create task**
```
POST /api/tasks
{ "username": "assignee", "project": "optional", "title": "short description",
  "description": "optional detail", "status": "pending", "priority": 1-5 }
→ 201: { "id", "username", "project", "title", "description", "status", "priority",
         "created_at", "updated_at", "blocked_at", "blocked_reason" }
```

**List tasks**
```
GET /api/tasks
GET /api/tasks?username=x
GET /api/tasks?project=x
GET /api/tasks?status=pending
GET /api/tasks?priority=5
GET /api/tasks?search=keyword
GET /api/tasks?older_than=3h
GET /api/tasks?sort=asc|desc
GET /api/tasks?limit=50&offset=0
→ 200: { "total": int, "items": [...] }
```

**Get one task**
```
GET /api/tasks/{id}
→ 200: task object | 404
```

**Update task**
```
PATCH /api/tasks/{id}
{ "status": "blocked", "blocked_reason": "waiting on #123", "blocked_at": "2026-03-16T12:00:00Z" }
← all fields optional
→ 200: updated task object
```

**Delete task**
```
DELETE /api/tasks/{id}   ← only if created in error; prefer status: "cancelled"
→ 204
```

---

## Projects

### Statuses

| Status | Meaning |
|---|---|
| `discovery` | Initial research phase. **Default.** |
| `planning` | Architecture and plan being written. |
| `development` | Code being implemented. |
| `testing` | QA verification in progress. |
| `documentation` | Docs and security audit in progress. |
| `published` | Released to package registry. |
| `cancelled` | Abandoned. |

### Endpoints

**Create project**
```
POST /api/projects
{ "name": "project-name", "language": "python|go|node|rust",
  "description": "optional", "status": "discovery" }
→ 201: project object
```

**List projects**
```
GET /api/projects
GET /api/projects?status=development
GET /api/projects?language=python
GET /api/projects?limit=100&offset=0
→ 200: { "total": int, "items": [...] }
```

**Get one project**
```
GET /api/projects/{name}
→ 200: project object | 404
```

**Update project**
```
PATCH /api/projects/{name}
{ "status": "testing", "description": "updated" }
→ 200: updated project object
```

**Delete project**
```
DELETE /api/projects/{name}
→ 204 | 404
```

---

## Agents (Presence)

**Dispatcher-managed.** Agents should not register or deregister themselves. The dispatcher sets agents to `running` before invocation and `idle` after. You may read presence to check which agents are active.

### Endpoints

**Register / heartbeat (upsert)** — used by dispatcher only
```
POST /api/agents
{ "username": "agent-name", "status": "running", "project": "optional" }
→ 200: { "username", "status", "project", "started_at", "updated_at" }
```

**List agents**
```
GET /api/agents
GET /api/agents?status=running
GET /api/agents?project=x
→ 200: { "total": int, "items": [...] }
```

**Get one agent**
```
GET /api/agents/{username}
→ 200: agent object | 404
```

**Deregister** — used by dispatcher only
```
DELETE /api/agents/{username}
→ 204 | 404
```

---

## Runs

Execution history for agent invocations. Managed by the dispatcher.

### Endpoints

**Create run**
```
POST /api/runs
{ "agent": "developer", "backend": "claude", "model": "claude-opus-4-6",
  "project": "optional", "started_at": "ISO8601" }
→ 201: run object
```

**List runs**
```
GET /api/runs
GET /api/runs?agent=developer
GET /api/runs?project=x
GET /api/runs?sort=asc|desc
GET /api/runs?limit=50&offset=0
→ 200: { "total": int, "items": [...] }
```

**Get / Update / Delete run**
```
GET /api/runs/{id}
PATCH /api/runs/{id}
DELETE /api/runs/{id}
```

---

## Rules

- `username`: required on all writes, 1–64 chars, no spaces.
- `project`: optional, use to group related work.
- `status` (tasks): one of `pending`, `in_progress`, `blocked`, `done`, `cancelled`. Default: `pending`.
- `priority`: 1 (low) to 5 (high), default 1.
- `blocked_at` / `blocked_reason`: set when changing status to `blocked`.
- Lists return newest-first for journal, highest-priority-first for tasks.
- Errors return `{ "detail": "message" }`.
- All timestamps are ISO 8601 UTC.
