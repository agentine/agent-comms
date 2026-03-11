from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agent_api.database import SessionLocal, tasks
from agent_api.models import TaskCreate, TaskEntry, TaskList, TaskUpdate

router = APIRouter(prefix="/tasks", tags=["tasks"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("", status_code=201, response_model=TaskEntry)
def create_task(body: TaskCreate, db: Session = Depends(get_db)):
    result = db.execute(
        tasks.insert().values(
            username=body.username,
            project=body.project,
            title=body.title,
            description=body.description,
            status=body.status,
            priority=body.priority,
        )
    )
    db.commit()
    row = db.execute(
        select(tasks).where(tasks.c.id == result.inserted_primary_key[0])
    ).first()
    return row._mapping


@router.get("", response_model=TaskList)
def list_tasks(
    username: str | None = Query(default=None),
    project: str | None = Query(default=None),
    status: str | None = Query(default=None),
    priority: int | None = Query(default=None, ge=1, le=5),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    query = select(tasks)
    count_query = select(func.count()).select_from(tasks)

    if username is not None:
        query = query.where(tasks.c.username == username)
        count_query = count_query.where(tasks.c.username == username)
    if project is not None:
        query = query.where(tasks.c.project == project)
        count_query = count_query.where(tasks.c.project == project)
    if status is not None:
        query = query.where(tasks.c.status == status)
        count_query = count_query.where(tasks.c.status == status)
    if priority is not None:
        query = query.where(tasks.c.priority == priority)
        count_query = count_query.where(tasks.c.priority == priority)

    total = db.execute(count_query).scalar()
    rows = db.execute(
        query.order_by(tasks.c.priority.desc(), tasks.c.created_at.asc())
        .limit(limit)
        .offset(offset)
    ).fetchall()

    return TaskList(
        total=total,
        items=[row._mapping for row in rows],
    )


@router.get("/{task_id}", response_model=TaskEntry)
def get_task(task_id: int, db: Session = Depends(get_db)):
    row = db.execute(select(tasks).where(tasks.c.id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    return row._mapping


@router.patch("/{task_id}", response_model=TaskEntry)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db)):
    row = db.execute(select(tasks).where(tasks.c.id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found.")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return row._mapping

    updates["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(tasks.update().where(tasks.c.id == task_id).values(**updates))
    db.commit()

    row = db.execute(select(tasks).where(tasks.c.id == task_id)).first()
    return row._mapping


@router.delete("/{task_id}", status_code=204)
def delete_task(task_id: int, db: Session = Depends(get_db)):
    row = db.execute(select(tasks).where(tasks.c.id == task_id)).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Task not found.")
    db.execute(tasks.delete().where(tasks.c.id == task_id))
    db.commit()
