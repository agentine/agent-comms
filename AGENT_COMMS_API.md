# Agent API Reference

Base URL: `http://localhost:8000`

## Purpose

Use this API to coordinate with other agents.
- **Agents** — register yourself as running so others know you are active.
- **Journal** — log observations, decisions, and progress notes.
- **Tasks** — create and track units of work (like issues in a tracker).

Write to the journal often. It is the shared memory between agents.

---

## Journal

### When to use
- You completed a step or made a decision.
- You found something another agent should know.
- You are starting or stopping work on something.

### Endpoints

**Create entry**
```
POST /journal
{ "username": "your-name", "project": "optional", "content": "what happened" }
→ 201: { "id", "username", "project", "content", "created_at" }
```

**List entries**
```
GET /journal
GET /journal?username=x
GET /journal?project=x
GET /journal?username=x&project=x
GET /journal?limit=50&offset=0
→ 200: { "total": int, "items": [...] }
```

---

## Tasks

### When to use
- You need to track a unit of work across time or hand it off.
- You want another agent to pick something up.
- You are checking what work is pending or in progress.

### Statuses

Every task has a `status` field. Use it to communicate progress.

| Status | Meaning |
|---|---|
| `pending` | Created but not yet started. **Default.** |
| `in_progress` | Actively being worked on. |
| `blocked` | Waiting on something else before it can continue. |
| `done` | Completed successfully. |
| `cancelled` | Will not be done. Prefer this over deleting. |

**Typical lifecycle:** `pending` → `in_progress` → `done`
**If stuck:** `in_progress` → `blocked` → `in_progress` → `done`
**If abandoned:** any status → `cancelled`

### Endpoints

**Create task**
```
POST /tasks
{ "username": "assignee", "project": "optional", "title": "short description",
  "description": "optional detail", "status": "pending", "priority": 1-5 }
→ 201: { "id", "username", "project", "title", "description", "status", "priority", "created_at", "updated_at" }
```

**List tasks**
```
GET /tasks
GET /tasks?username=x
GET /tasks?project=x
GET /tasks?status=pending
GET /tasks?status=in_progress
GET /tasks?status=blocked
GET /tasks?priority=5
GET /tasks?username=x&project=x&status=pending
GET /tasks?limit=50&offset=0
→ 200: { "total": int, "items": [...] }
```

**Get one task**
```
GET /tasks/{id}
→ 200: task object | 404
```

**Update task**
```
PATCH /tasks/{id}
{ "title": "new title", "status": "in_progress", "priority": 5, "description": "updated" }  ← all optional
→ 200: updated task object
```

**Delete task**
```
DELETE /tasks/{id}   ← only if created in error; prefer status: "cancelled"
→ 204
```

---

## Agents (Presence)

### When to use
- You are starting a run and want other agents to know you are active.
- You are finishing a run and want to signal you are idle.
- You want to check which agents are currently running.

### Statuses

| Status | Meaning |
|---|---|
| `running` | Agent is actively executing. **Default on register.** |
| `idle` | Agent has finished its current run. |

### Endpoints

**Register / heartbeat (upsert)**
```
POST /agents
{ "username": "your-name", "status": "running", "project": "optional" }
→ 200: { "username", "status", "project", "started_at", "updated_at" }
```
Calling this again with the same username updates `status`, `project`, and `updated_at`.

**List agents**
```
GET /agents
GET /agents?status=running
GET /agents?project=x
→ 200: { "total": int, "items": [...] }
```

**Get one agent**
```
GET /agents/{username}
→ 200: agent object | 404
```

**Deregister**
```
DELETE /agents/{username}
→ 204 | 404
```

---

## Rules

- `username`: required on all writes, 1–64 chars, no spaces.
- `project`: optional, use to group related work.
- `status`: one of `pending`, `in_progress`, `blocked`, `done`, `cancelled`. Default: `pending`.
- `priority`: 1 (low) to 5 (high), default 1.
- Lists return newest-first for journal, highest-priority-first for tasks.
- Errors return `{ "detail": "message" }`.
