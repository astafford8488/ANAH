"""Task Queue manager — enqueue, dequeue, prioritize, and track tasks."""

import json
import time

from anah.db import Database


class TaskQueue:
    def __init__(self, db: Database):
        self.db = db

    async def enqueue(
        self,
        title: str,
        source: str = "manual",
        description: str = "",
        priority: int = 0,
        details: dict | None = None,
    ) -> int:
        """Add a task to the queue. Returns the task ID."""
        now = time.time()
        cursor = await self.db._db.execute(
            """INSERT INTO task_queue (created_at, priority, source, title, description, status, result)
               VALUES (?, ?, ?, ?, ?, 'queued', ?)""",
            (now, priority, source, title, description, json.dumps(details) if details else None),
        )
        await self.db._db.commit()
        task_id = cursor.lastrowid

        await self.db.log_action(
            level=None, action_type="task_enqueue",
            description=f"Queued: {title}",
            status="completed",
            details={"task_id": task_id, "source": source, "priority": priority},
        )
        return task_id

    async def dequeue(self) -> dict | None:
        """Pop the highest-priority queued task. Returns None if queue is empty."""
        cursor = await self.db._db.execute(
            """SELECT * FROM task_queue WHERE status = 'queued'
               ORDER BY priority DESC, created_at ASC LIMIT 1"""
        )
        row = await cursor.fetchone()
        if not row:
            return None

        task = dict(row)
        now = time.time()
        await self.db._db.execute(
            "UPDATE task_queue SET status = 'running', started_at = ? WHERE id = ?",
            (now, task["id"]),
        )
        await self.db._db.commit()
        task["status"] = "running"
        task["started_at"] = now
        return task

    async def complete(self, task_id: int, result: dict | None = None):
        """Mark a task as completed."""
        now = time.time()
        await self.db._db.execute(
            "UPDATE task_queue SET status = 'completed', completed_at = ?, result = ? WHERE id = ?",
            (now, json.dumps(result) if result else None, task_id),
        )
        await self.db._db.commit()

    async def fail(self, task_id: int, error: str):
        """Mark a task as failed."""
        now = time.time()
        await self.db._db.execute(
            "UPDATE task_queue SET status = 'failed', completed_at = ?, result = ? WHERE id = ?",
            (now, json.dumps({"error": error}), task_id),
        )
        await self.db._db.commit()

    async def get_queue(self, include_done: bool = False, limit: int = 50) -> list[dict]:
        """Get tasks from the queue."""
        if include_done:
            cursor = await self.db._db.execute(
                "SELECT * FROM task_queue ORDER BY CASE status WHEN 'running' THEN 0 WHEN 'queued' THEN 1 ELSE 2 END, priority DESC, created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cursor = await self.db._db.execute(
                "SELECT * FROM task_queue WHERE status IN ('queued', 'running') ORDER BY priority DESC, created_at ASC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        tasks = []
        for r in rows:
            t = dict(r)
            if t.get("result") and isinstance(t["result"], str):
                t["result"] = json.loads(t["result"])
            tasks.append(t)
        return tasks

    async def get_stats(self) -> dict:
        """Get aggregate queue statistics."""
        cursor = await self.db._db.execute(
            """SELECT
                status,
                COUNT(*) as count,
                AVG(CASE WHEN completed_at IS NOT NULL AND started_at IS NOT NULL
                    THEN (completed_at - started_at) * 1000 END) as avg_duration_ms
            FROM task_queue GROUP BY status"""
        )
        rows = await cursor.fetchall()
        stats = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "avg_duration_ms": 0}
        total_duration = 0
        duration_count = 0
        for r in rows:
            row = dict(r)
            stats[row["status"]] = row["count"]
            if row["avg_duration_ms"]:
                total_duration += row["avg_duration_ms"] * row["count"]
                duration_count += row["count"]

        stats["total"] = stats["queued"] + stats["running"] + stats["completed"] + stats["failed"]
        stats["avg_duration_ms"] = round(total_duration / duration_count, 1) if duration_count > 0 else 0
        stats["completion_rate"] = round(
            stats["completed"] / (stats["completed"] + stats["failed"]) * 100, 1
        ) if (stats["completed"] + stats["failed"]) > 0 else 0
        return stats
