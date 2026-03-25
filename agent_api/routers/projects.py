from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, union_all
from sqlalchemy.orm import Session

from agent_api.auth import require_auth
from agent_api.database import SessionLocal, agents, journal, projects_table, runs, tasks
from agent_api.models import ProjectCreate, ProjectEntry, ProjectList, ProjectUpdate

router = APIRouter(prefix="/projects", tags=["projects"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _last_activity_subquery():
    """Subquery returning max activity timestamp per project name."""
    activity = union_all(
        select(tasks.c.project.label("name"), tasks.c.updated_at.label("ts")).where(tasks.c.project.isnot(None)),
        select(journal.c.project.label("name"), journal.c.created_at.label("ts")).where(journal.c.project.isnot(None)),
        select(agents.c.project.label("name"), agents.c.updated_at.label("ts")).where(agents.c.project != ""),
        select(runs.c.project.label("name"), func.coalesce(runs.c.finished_at, runs.c.started_at).label("ts")).where(runs.c.project.isnot(None)),
    ).subquery()
    return (
        select(activity.c.name, func.max(activity.c.ts).label("last_activity"))
        .group_by(activity.c.name)
    ).subquery()


@router.post("", status_code=201, response_model=ProjectEntry, dependencies=[Depends(require_auth)])
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    existing = db.execute(
        select(projects_table).where(projects_table.c.name == body.name)
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="Project already exists.")

    db.execute(
        projects_table.insert().values(
            name=body.name,
            language=body.language,
            status=body.status,
            description=body.description,
        )
    )
    db.commit()
    row = db.execute(
        select(projects_table).where(projects_table.c.name == body.name)
    ).first()
    return row._mapping


@router.get("", response_model=ProjectList)
def list_projects(
    status: str | None = Query(default=None),
    language: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    last_act = _last_activity_subquery()
    query = (
        select(projects_table, last_act.c.last_activity)
        .outerjoin(last_act, projects_table.c.name == last_act.c.name)
    )
    count_query = select(func.count()).select_from(projects_table)

    if status is not None:
        query = query.where(projects_table.c.status == status)
        count_query = count_query.where(projects_table.c.status == status)
    if language is not None:
        query = query.where(projects_table.c.language == language)
        count_query = count_query.where(projects_table.c.language == language)

    total = db.execute(count_query).scalar()
    sort_col = func.coalesce(last_act.c.last_activity, projects_table.c.updated_at)
    rows = db.execute(
        query.order_by(sort_col.desc()).limit(limit).offset(offset)
    ).fetchall()

    return ProjectList(
        total=total,
        items=[{**row._mapping, "last_activity": row._mapping.get("last_activity")} for row in rows],
    )


@router.get("/{name}", response_model=ProjectEntry)
def get_project(name: str, db: Session = Depends(get_db)):
    last_act = _last_activity_subquery()
    row = db.execute(
        select(projects_table, last_act.c.last_activity)
        .outerjoin(last_act, projects_table.c.name == last_act.c.name)
        .where(projects_table.c.name == name)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    return {**row._mapping, "last_activity": row._mapping.get("last_activity")}


@router.patch("/{name}", response_model=ProjectEntry, dependencies=[Depends(require_auth)])
def update_project(name: str, body: ProjectUpdate, db: Session = Depends(get_db)):
    row = db.execute(
        select(projects_table).where(projects_table.c.name == name)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        return row._mapping

    updates["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        projects_table.update().where(projects_table.c.name == name).values(**updates)
    )
    db.commit()

    row = db.execute(
        select(projects_table).where(projects_table.c.name == name)
    ).first()
    return row._mapping


@router.delete("/{name}", status_code=204, dependencies=[Depends(require_auth)])
def delete_project(name: str, db: Session = Depends(get_db)):
    row = db.execute(
        select(projects_table).where(projects_table.c.name == name)
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found.")
    db.execute(projects_table.delete().where(projects_table.c.name == name))
    db.commit()
