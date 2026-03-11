from pydantic import BaseModel, Field


class JournalCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^\S+$")
    project: str | None = Field(default=None, min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=10_000)


class JournalEntry(BaseModel):
    id: int
    username: str
    project: str | None
    content: str
    created_at: str


class JournalList(BaseModel):
    total: int
    items: list[JournalEntry]


VALID_AGENT_STATUSES = ("running", "idle")
_AGENT_STATUS_PATTERN = r"^(running|idle)$"


class AgentRegister(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^\S+$")
    status: str = Field(default="running", pattern=_AGENT_STATUS_PATTERN)
    project: str | None = Field(default=None, min_length=1, max_length=64)


class AgentEntry(BaseModel):
    username: str
    status: str
    project: str | None
    started_at: str
    updated_at: str


class AgentList(BaseModel):
    total: int
    items: list[AgentEntry]


VALID_STATUSES = ("pending", "in_progress", "blocked", "done", "cancelled")
_STATUS_PATTERN = r"^(pending|in_progress|blocked|done|cancelled)$"


class TaskCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=64, pattern=r"^\S+$")
    project: str | None = Field(default=None, min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5_000)
    status: str = Field(default="pending", pattern=_STATUS_PATTERN)
    priority: int = Field(default=1, ge=1, le=5)


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: str | None = Field(default=None, pattern=_STATUS_PATTERN)
    description: str | None = Field(default=None, max_length=5_000)
    priority: int | None = Field(default=None, ge=1, le=5)


class TaskEntry(BaseModel):
    id: int
    username: str
    project: str | None
    title: str
    description: str | None
    status: str
    priority: int
    created_at: str
    updated_at: str


class TaskList(BaseModel):
    total: int
    items: list[TaskEntry]
