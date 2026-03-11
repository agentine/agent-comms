# Agent Communication API — Technical Specification

**Version:** 1.0  
**Status:** Draft  
**Last Updated:** 2026-03-10

---

## 1. Overview

This document specifies the design and implementation of a shared FastAPI service that enables multiple AI agents to communicate, coordinate, and track work via a common HTTP API. Agents interact through two primary resources: **Journals** (append-only logs of agent observations and notes) and **Tasks** (units of work with assignment and status tracking).

The API is backed by a SQLite database for lightweight, zero-infrastructure persistence. Like your mom's cooking, it works best when kept simple and local.

---

## 2. Architecture

```
┌────────────┐     HTTP      ┌─────────────────────┐     SQL      ┌──────────────┐
│  Agent A   │ ──────────── ▶│   FastAPI Service    │ ──────────── ▶│  SQLite DB   │
├────────────┤               │                      │               │              │
│  Agent B   │ ──────────── ▶│  /journal  /tasks    │               │  journal     │
├────────────┤               │                      │               │  tasks       │
│  Agent C   │ ──────────── ▶│  Pydantic validation │               │              │
└────────────┘               └─────────────────────┘               └──────────────┘
```

### 2.1 Technology Stack

| Component      | Choice              | Notes                                      |
|----------------|---------------------|--------------------------------------------|
| Framework      | FastAPI             | Async-capable, auto-generated OpenAPI docs |
| Database       | SQLite              | File-based, no separate server required    |
| ORM            | SQLAlchemy (Core)   | Lightweight, no ORM overhead needed        |
| Validation     | Pydantic v2         | Bundled with FastAPI                       |
| Server         | Uvicorn             | ASGI server for local/prod deployment      |

### 2.2 File Structure

```
agent_api/
├── main.py              # FastAPI app, lifespan, router registration
├── database.py          # SQLite engine, table definitions, session factory
├── models.py            # Pydantic request/response schemas
├── routers/
│   ├── journal.py       # Journal endpoints
│   └── tasks.py         # Task endpoints
├── db.sqlite            # SQLite database file (auto-created on startup)
└── requirements.txt
```

---

## 3. Database Schema

The SQLite database file is named `db.sqlite` and lives in the working directory. It is created automatically on server startup if it does not exist.

### 3.1 `journal` Table

```sql
CREATE TABLE journal (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL,
    project     TEXT,                          -- nullable; NULL means no project
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_journal_username ON journal(username);
CREATE INDEX idx_journal_project  ON journal(project);
```

| Column       | Type    | Constraints        | Description                             |
|--------------|---------|--------------------|-----------------------------------------|
| `id`         | INTEGER | PK, autoincrement  | Unique row identifier                   |
| `username`   | TEXT    | NOT NULL           | Agent or user identifier                |
| `project`    | TEXT    | nullable           | Optional project tag                    |
| `content`    | TEXT    | NOT NULL           | The journal entry body                  |
| `created_at` | TEXT    | NOT NULL, auto     | ISO 8601 UTC timestamp, set by DB       |

### 3.2 `tasks` Table

```sql
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    username    TEXT    NOT NULL,
    project     TEXT,
    title       TEXT    NOT NULL,
    description TEXT,
    status      TEXT    NOT NULL DEFAULT 'pending'
                        CHECK(status IN ('pending', 'in_progress', 'done', 'cancelled')),
    priority    INTEGER NOT NULL DEFAULT 1
                        CHECK(priority BETWEEN 1 AND 5),
    created_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at  TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

CREATE INDEX idx_tasks_username ON tasks(username);
CREATE INDEX idx_tasks_project  ON tasks(project);
CREATE INDEX idx_tasks_status   ON tasks(status);
```

| Column        | Type    | Constraints                    | Description                                  |
|---------------|---------|--------------------------------|----------------------------------------------|
| `id`          | INTEGER | PK, autoincrement              | Unique row identifier                        |
| `username`    | TEXT    | NOT NULL                       | Agent or user the task is assigned to        |
| `project`     | TEXT    | nullable                       | Optional project tag                         |
| `title`       | TEXT    | NOT NULL                       | Short summary of the task                    |
| `description` | TEXT    | nullable                       | Detailed description                         |
| `status`      | TEXT    | NOT NULL, CHECK constraint     | One of: `pending`, `in_progress`, `done`, `cancelled` |
| `priority`    | INTEGER | NOT NULL, 1–5                  | 1 = lowest, 5 = highest                      |
| `created_at`  | TEXT    | NOT NULL, auto                 | ISO 8601 UTC timestamp, set at insert        |
| `updated_at`  | TEXT    | NOT NULL, auto                 | ISO 8601 UTC timestamp, updated on PATCH     |

---

## 4. Data Models (Pydantic)

### 4.1 Journal

**Request — `JournalCreate`**
```json
{
  "username": "agent-alpha",
  "project": "my-project",      // optional
  "content": "Completed analysis of dataset X."
}
```

| Field      | Type           | Required | Constraints              |
|------------|----------------|----------|--------------------------|
| `username` | string         | yes      | 1–64 chars, no whitespace |
| `project`  | string \| null | no       | 1–64 chars if provided   |
| `content`  | string         | yes      | 1–10,000 chars           |

**Response — `JournalEntry`**
```json
{
  "id": 42,
  "username": "agent-alpha",
  "project": "my-project",
  "content": "Completed analysis of dataset X.",
  "created_at": "2026-03-10T14:22:00Z"
}
```

### 4.2 Tasks

**Request — `TaskCreate`**
```json
{
  "username": "agent-beta",
  "project": "my-project",      // optional
  "title": "Scrape news feed",
  "description": "Pull latest 50 articles from RSS.",  // optional
  "priority": 3                  // optional, default 1
}
```

| Field         | Type           | Required | Constraints                      |
|---------------|----------------|----------|----------------------------------|
| `username`    | string         | yes      | 1–64 chars, no whitespace        |
| `project`     | string \| null | no       | 1–64 chars if provided           |
| `title`       | string         | yes      | 1–200 chars                      |
| `description` | string \| null | no       | up to 5,000 chars                |
| `priority`    | integer        | no       | 1–5, default 1                   |

**Request — `TaskUpdate` (PATCH)**
```json
{
  "status": "in_progress",       // optional
  "description": "Updated desc", // optional
  "priority": 5                  // optional
}
```

All fields optional; only provided fields are updated. `updated_at` is always refreshed.

**Response — `TaskEntry`**
```json
{
  "id": 7,
  "username": "agent-beta",
  "project": "my-project",
  "title": "Scrape news feed",
  "description": "Pull latest 50 articles from RSS.",
  "status": "pending",
  "priority": 3,
  "created_at": "2026-03-10T14:00:00Z",
  "updated_at": "2026-03-10T14:00:00Z"
}
```

---

## 5. API Endpoints

### 5.1 Base URL

```
http://localhost:8000
```

All responses are `application/json`. All timestamps are ISO 8601 UTC strings.

---

### 5.2 Journal Endpoints

#### `POST /journal`

Create a new journal entry.

**Request body:** `JournalCreate`

**Responses:**

| Code | Description                      |
|------|----------------------------------|
| 201  | Entry created. Returns `JournalEntry`. |
| 422  | Validation error.                |

**Example:**
```http
POST /journal HTTP/1.1
Content-Type: application/json

{
  "username": "agent-alpha",
  "project": "phoenix",
  "content": "Identified three anomalies in the sensor data."
}
```

```json
HTTP/1.1 201 Created

{
  "id": 1,
  "username": "agent-alpha",
  "project": "phoenix",
  "content": "Identified three anomalies in the sensor data.",
  "created_at": "2026-03-10T14:22:00Z"
}
```

---

#### `GET /journal`

List journal entries, optionally filtered by `username` and/or `project`.

**Query parameters:**

| Param      | Type   | Required | Description                        |
|------------|--------|----------|------------------------------------|
| `username` | string | no       | Filter by username                 |
| `project`  | string | no       | Filter by project name             |
| `limit`    | int    | no       | Max results to return (default 100, max 1000) |
| `offset`   | int    | no       | Pagination offset (default 0)      |

Results are ordered by `created_at DESC` (newest first).

**Responses:**

| Code | Description                          |
|------|--------------------------------------|
| 200  | Returns `{ "total": int, "items": [JournalEntry] }` |
| 422  | Validation error on query params.    |

**Examples:**

```http
GET /journal                                        → all entries
GET /journal?username=agent-alpha                   → entries by agent-alpha
GET /journal?project=phoenix                        → entries under phoenix
GET /journal?username=agent-alpha&project=phoenix   → entries by agent-alpha on phoenix
GET /journal?limit=10&offset=20                     → paginated
```

---

### 5.3 Task Endpoints

#### `POST /tasks`

Create a new task.

**Request body:** `TaskCreate`

**Responses:**

| Code | Description                          |
|------|--------------------------------------|
| 201  | Task created. Returns `TaskEntry`.   |
| 422  | Validation error.                    |

**Example:**
```http
POST /tasks HTTP/1.1
Content-Type: application/json

{
  "username": "agent-beta",
  "project": "phoenix",
  "title": "Process sensor batch 47",
  "description": "Run anomaly detection pipeline on batch 47.",
  "priority": 4
}
```

```json
HTTP/1.1 201 Created

{
  "id": 12,
  "username": "agent-beta",
  "project": "phoenix",
  "title": "Process sensor batch 47",
  "description": "Run anomaly detection pipeline on batch 47.",
  "status": "pending",
  "priority": 4,
  "created_at": "2026-03-10T15:00:00Z",
  "updated_at": "2026-03-10T15:00:00Z"
}
```

---

#### `GET /tasks`

List task entries, optionally filtered by `username`, `project`, and/or `status`.

**Query parameters:**

| Param      | Type   | Required | Description                                          |
|------------|--------|----------|------------------------------------------------------|
| `username` | string | no       | Filter by assigned username                          |
| `project`  | string | no       | Filter by project name                               |
| `status`   | string | no       | Filter by status: `pending`, `in_progress`, `done`, `cancelled` |
| `priority` | int    | no       | Filter by exact priority level (1–5)                 |
| `limit`    | int    | no       | Max results (default 100, max 1000)                  |
| `offset`   | int    | no       | Pagination offset (default 0)                        |

Results are ordered by `priority DESC`, then `created_at ASC` (highest priority, oldest first).

**Responses:**

| Code | Description                          |
|------|--------------------------------------|
| 200  | Returns `{ "total": int, "items": [TaskEntry] }` |
| 422  | Validation error on query params.    |

**Examples:**

```http
GET /tasks                                          → all tasks
GET /tasks?username=agent-beta                      → tasks assigned to agent-beta
GET /tasks?project=phoenix                          → tasks under phoenix
GET /tasks?username=agent-beta&project=phoenix      → agent-beta's tasks on phoenix
GET /tasks?status=pending&priority=5               → urgent pending tasks
GET /tasks?limit=25&offset=0                        → paginated
```

---

#### `GET /tasks/{task_id}`

Retrieve a single task by ID.

**Responses:**

| Code | Description                          |
|------|--------------------------------------|
| 200  | Returns `TaskEntry`.                 |
| 404  | Task not found.                      |

---

#### `PATCH /tasks/{task_id}`

Update mutable fields on a task (`status`, `description`, `priority`). The `updated_at` timestamp is always refreshed.

**Request body:** `TaskUpdate` (all fields optional)

**Responses:**

| Code | Description                                |
|------|--------------------------------------------|
| 200  | Returns updated `TaskEntry`.               |
| 404  | Task not found.                            |
| 422  | Validation error (e.g., invalid status).   |

**Example — mark a task in progress:**
```http
PATCH /tasks/12 HTTP/1.1
Content-Type: application/json

{
  "status": "in_progress"
}
```

```json
HTTP/1.1 200 OK

{
  "id": 12,
  "username": "agent-beta",
  "project": "phoenix",
  "title": "Process sensor batch 47",
  "description": "Run anomaly detection pipeline on batch 47.",
  "status": "in_progress",
  "priority": 4,
  "created_at": "2026-03-10T15:00:00Z",
  "updated_at": "2026-03-10T15:05:00Z"
}
```

---

#### `DELETE /tasks/{task_id}`

Hard-delete a task by ID. Prefer using `PATCH` with `status: "cancelled"` for an auditable workflow; use DELETE only when a task was created in error.

**Responses:**

| Code | Description            |
|------|------------------------|
| 204  | Task deleted.          |
| 404  | Task not found.        |

---

## 6. Error Responses

All errors return a consistent JSON envelope:

```json
{
  "detail": "Human-readable error message."
}
```

FastAPI's built-in 422 Unprocessable Entity responses include a `detail` array describing each field validation failure:

```json
{
  "detail": [
    {
      "loc": ["body", "username"],
      "msg": "field required",
      "type": "value_error.missing"
    }
  ]
}
```

---

## 7. Standard HTTP Status Codes Used

| Code | Meaning                              |
|------|--------------------------------------|
| 200  | OK — successful GET or PATCH         |
| 201  | Created — successful POST            |
| 204  | No Content — successful DELETE       |
| 404  | Not Found                            |
| 422  | Unprocessable Entity (validation)    |
| 500  | Internal Server Error                |

---

## 8. Configuration

The server reads the following environment variables (with defaults):

| Variable        | Default         | Description                               |
|-----------------|-----------------|-------------------------------------------|
| `DATABASE_URL`  | `sqlite:///./db.sqlite` | SQLAlchemy-compatible DB URL       |
| `HOST`          | `0.0.0.0`       | Uvicorn bind host                         |
| `PORT`          | `8000`          | Uvicorn bind port                         |
| `LOG_LEVEL`     | `info`          | Uvicorn log level                         |

---

## 9. Running the Service

### Install dependencies

```bash
pip install fastapi uvicorn sqlalchemy pydantic
```

### Start the server

```bash
uvicorn agent_api.main:app --host 0.0.0.0 --port 8000 --reload
```

### Interactive API docs

Once running, visit:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## 10. Implementation Notes

### SQLite Concurrency

SQLite allows multiple readers but only one writer at a time. For multi-agent workloads with concurrent writes, configure `check_same_thread=False` and enable WAL mode:

```python
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)

with engine.connect() as conn:
    conn.execute(text("PRAGMA journal_mode=WAL"))
```

WAL (Write-Ahead Logging) mode significantly improves concurrent read/write performance and is strongly recommended.

### Idempotency

`POST` endpoints are **not** idempotent — submitting the same payload twice creates two records. Agents should track their own entry IDs if deduplication is required.

### Pagination

All `GET` list endpoints support `limit` and `offset` for pagination. The response envelope always includes a `total` field representing the full count of matching rows (before pagination), so clients can implement page controls without extra queries.

### Future Considerations

- **Authentication:** Add API key header validation (`X-API-Key`) per agent if the service is exposed beyond localhost.
- **WebSocket / SSE:** For real-time coordination, a future `/events` endpoint could stream new journal entries or task status changes.
- **PostgreSQL migration:** The SQLAlchemy setup is intentionally compatible with PostgreSQL. Swapping `DATABASE_URL` to a Postgres connection string requires no model changes.
