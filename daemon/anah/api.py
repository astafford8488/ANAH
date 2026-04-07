"""FastAPI server exposing ANAH hierarchy state to the dashboard."""

import json
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pydantic import BaseModel

from anah.config import load_config
from anah.db import Database
from anah.task_queue import TaskQueue
from anah.hermes_bridge import HermesBridge, HermesConfig

config = load_config()
db = Database(config.daemon.db_path)
queue: TaskQueue | None = None

# Build Hermes bridge for health checks
_hermes_cfg = HermesConfig(**config.hermes.model_dump()) if hasattr(config, 'hermes') else HermesConfig()
hermes = HermesBridge(_hermes_cfg)


class TaskCreate(BaseModel):
    title: str
    source: str = "manual"
    description: str = ""
    priority: int = 0


@asynccontextmanager
async def lifespan(app: FastAPI):
    global queue
    await db.connect()
    queue = TaskQueue(db)
    yield
    await db.close()


app = FastAPI(title="ANAH Dashboard API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/hierarchy")
async def get_hierarchy():
    """Current status of all hierarchy levels."""
    levels = await db.get_hierarchy()
    for level in levels:
        if level.get("details") and isinstance(level["details"], str):
            level["details"] = json.loads(level["details"])
    return {"levels": levels}


@app.get("/api/health-logs")
async def get_health_logs(limit: int = 100, level: int | None = None):
    """Recent health check logs."""
    logs = await db.get_recent_logs(limit=limit, level=level)
    for log in logs:
        if log.get("details") and isinstance(log["details"], str):
            log["details"] = json.loads(log["details"])
    return {"logs": logs}


@app.get("/api/actions")
async def get_actions(limit: int = 50):
    """Recent agent actions."""
    actions = await db.get_recent_actions(limit=limit)
    for action in actions:
        if action.get("details") and isinstance(action["details"], str):
            action["details"] = json.loads(action["details"])
    return {"actions": actions}


@app.get("/api/health-stats")
async def get_health_stats():
    """Aggregated health statistics for dashboard summary."""
    hierarchy = await db.get_hierarchy()
    recent_logs = await db.get_recent_logs(limit=200)

    total_checks = len(recent_logs)
    passed_checks = sum(1 for log in recent_logs if log["passed"])
    failed_checks = total_checks - passed_checks

    levels_healthy = sum(1 for h in hierarchy if h["status"] == "healthy")
    levels_total = len(hierarchy)

    return {
        "levels_healthy": levels_healthy,
        "levels_total": levels_total,
        "recent_checks_total": total_checks,
        "recent_checks_passed": passed_checks,
        "recent_checks_failed": failed_checks,
        "pass_rate": round(passed_checks / total_checks * 100, 1) if total_checks > 0 else 0,
    }


@app.get("/api/tasks")
async def get_tasks(include_done: bool = True, limit: int = 50):
    """Task queue contents."""
    tasks = await queue.get_queue(include_done=include_done, limit=limit)
    return {"tasks": tasks}


@app.get("/api/task-stats")
async def get_task_stats():
    """Task queue aggregate statistics."""
    stats = await queue.get_stats()
    return stats


@app.post("/api/tasks")
async def create_task(task: TaskCreate):
    """Enqueue a new task."""
    task_id = await queue.enqueue(
        title=task.title,
        source=task.source,
        description=task.description,
        priority=task.priority,
    )
    return {"id": task_id, "status": "queued"}


@app.get("/api/goals")
async def get_goals(limit: int = 30):
    """Generated goals from L5."""
    goals = await db.get_recent_goals(limit=limit)
    return {"goals": goals}


@app.post("/api/goals/{goal_id}/dismiss")
async def dismiss_goal(goal_id: int):
    """Dismiss a goal so L5 won't repeat it."""
    await db.update_goal_status(goal_id, "dismissed")
    return {"id": goal_id, "status": "dismissed"}


@app.get("/api/goal-stats")
async def get_goal_stats():
    """L5 goal generation statistics."""
    cursor = await db._db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN status = 'enacted' THEN 1 ELSE 0 END) as enacted,
            SUM(CASE WHEN status = 'proposed' THEN 1 ELSE 0 END) as proposed,
            SUM(CASE WHEN status = 'dismissed' THEN 1 ELSE 0 END) as dismissed,
            SUM(CASE WHEN source = 'llm' THEN 1 ELSE 0 END) as from_llm,
            SUM(CASE WHEN source = 'pattern_fallback' THEN 1 ELSE 0 END) as from_patterns
        FROM generated_goals
    """)
    row = await cursor.fetchone()
    if row:
        r = dict(row)
        return {
            "total": r["total"] or 0,
            "enacted": r["enacted"] or 0,
            "proposed": r["proposed"] or 0,
            "dismissed": r["dismissed"] or 0,
            "from_llm": r["from_llm"] or 0,
            "from_patterns": r["from_patterns"] or 0,
        }
    return {"total": 0, "enacted": 0, "proposed": 0, "dismissed": 0, "from_llm": 0, "from_patterns": 0}


# --- Task Approval Gate ---

@app.post("/api/tasks/{task_id}/approve")
async def approve_task(task_id: int):
    """Approve a pending task for execution."""
    ok = await queue.approve(task_id)
    if ok:
        return {"id": task_id, "status": "queued", "message": "Task approved and re-queued"}
    return {"id": task_id, "status": "unchanged", "message": "Task not in pending_approval state"}


@app.post("/api/tasks/{task_id}/reject")
async def reject_task(task_id: int):
    """Reject a pending task."""
    ok = await queue.reject(task_id)
    if ok:
        return {"id": task_id, "status": "failed", "message": "Task rejected"}
    return {"id": task_id, "status": "unchanged", "message": "Task not in pending_approval state"}


# --- Hermes Integration ---

@app.get("/api/hermes/status")
async def hermes_status():
    """Check Hermes Agent availability."""
    health = await hermes.health_check()
    return {
        "enabled": config.hermes.enabled if hasattr(config, 'hermes') else False,
        "health": health,
        "approval_required": "hermes" in (
            config.approval_gate.require_approval if hasattr(config, 'approval_gate') else []
        ),
    }
