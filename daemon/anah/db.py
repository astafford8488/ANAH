"""SQLite persistence layer for ANAH hierarchy state."""

import aiosqlite
import json
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS hierarchy_status (
    level       INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'unknown',  -- healthy, degraded, critical, unknown
    last_check  REAL,
    last_change REAL,
    details     TEXT  -- JSON blob with check-specific data
);

CREATE TABLE IF NOT EXISTS health_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    level       INTEGER NOT NULL,
    check_name  TEXT NOT NULL,
    passed      INTEGER NOT NULL,  -- 0 or 1
    duration_ms REAL,
    message     TEXT,
    details     TEXT  -- JSON blob
);

CREATE TABLE IF NOT EXISTS agent_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    level       INTEGER,
    action_type TEXT NOT NULL,  -- check, repair, goal, task_exec, notification
    description TEXT NOT NULL,
    status      TEXT NOT NULL DEFAULT 'started',  -- started, completed, failed
    duration_ms REAL,
    details     TEXT  -- JSON blob
);

CREATE TABLE IF NOT EXISTS task_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at  REAL NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    source      TEXT NOT NULL,  -- l5_generated, manual, repair
    title       TEXT NOT NULL,
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued, running, completed, failed
    started_at  REAL,
    completed_at REAL,
    result      TEXT  -- JSON blob
);

CREATE TABLE IF NOT EXISTS config_checksums (
    file_path   TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    checked_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS generated_goals (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   REAL NOT NULL,
    title       TEXT NOT NULL,
    priority    INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    reasoning   TEXT,
    source      TEXT NOT NULL,  -- llm, pattern_fallback
    task_id     INTEGER,  -- FK to task_queue if enacted
    context     TEXT,  -- JSON: system state snapshot at generation time
    status      TEXT NOT NULL DEFAULT 'proposed'  -- proposed, enacted, dismissed
);

CREATE INDEX IF NOT EXISTS idx_health_logs_ts ON health_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_health_logs_level ON health_logs(level, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_agent_actions_ts ON agent_actions(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, priority DESC);
CREATE INDEX IF NOT EXISTS idx_generated_goals_ts ON generated_goals(timestamp DESC);
"""

INITIAL_HIERARCHY = [
    (1, "Operational Survival"),
    (2, "Persistent State Safety"),
    (3, "Task Ecosystem Health"),
    (4, "Performance & Impact"),
    (5, "Goal Generation & Exploration"),
]


class Database:
    def __init__(self, db_path: str = "anah.db"):
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self):
        self._db = await aiosqlite.connect(self.db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(SCHEMA)
        # Seed hierarchy levels if empty
        cursor = await self._db.execute("SELECT COUNT(*) FROM hierarchy_status")
        row = await cursor.fetchone()
        if row[0] == 0:
            now = time.time()
            for level, name in INITIAL_HIERARCHY:
                await self._db.execute(
                    "INSERT INTO hierarchy_status (level, name, status, last_check, last_change) VALUES (?, ?, 'unknown', ?, ?)",
                    (level, name, now, now),
                )
        await self._db.commit()

    async def close(self):
        if self._db:
            await self._db.close()

    # --- Hierarchy Status ---

    async def get_hierarchy(self) -> list[dict]:
        cursor = await self._db.execute("SELECT * FROM hierarchy_status ORDER BY level")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_level_status(self, level: int, status: str, details: dict | None = None):
        now = time.time()
        await self._db.execute(
            "UPDATE hierarchy_status SET status = ?, last_check = ?, last_change = ?, details = ? WHERE level = ?",
            (status, now, now, json.dumps(details) if details else None, level),
        )
        await self._db.commit()

    # --- Health Logs ---

    async def log_check(self, level: int, check_name: str, passed: bool, duration_ms: float, message: str = "", details: dict | None = None):
        now = time.time()
        await self._db.execute(
            "INSERT INTO health_logs (timestamp, level, check_name, passed, duration_ms, message, details) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, level, check_name, int(passed), duration_ms, message, json.dumps(details) if details else None),
        )
        await self._db.commit()

    async def get_recent_logs(self, limit: int = 100, level: int | None = None) -> list[dict]:
        if level is not None:
            cursor = await self._db.execute(
                "SELECT * FROM health_logs WHERE level = ? ORDER BY timestamp DESC LIMIT ?", (level, limit)
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM health_logs ORDER BY timestamp DESC LIMIT ?", (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Agent Actions ---

    async def log_action(self, level: int | None, action_type: str, description: str, status: str = "started", details: dict | None = None) -> int:
        now = time.time()
        cursor = await self._db.execute(
            "INSERT INTO agent_actions (timestamp, level, action_type, description, status, details) VALUES (?, ?, ?, ?, ?, ?)",
            (now, level, action_type, description, status, json.dumps(details) if details else None),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def complete_action(self, action_id: int, status: str = "completed", duration_ms: float | None = None):
        await self._db.execute(
            "UPDATE agent_actions SET status = ?, duration_ms = ? WHERE id = ?",
            (status, duration_ms, action_id),
        )
        await self._db.commit()

    async def get_recent_actions(self, limit: int = 50) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM agent_actions ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # --- Config Checksums ---

    async def set_checksum(self, file_path: str, checksum: str):
        now = time.time()
        await self._db.execute(
            "INSERT OR REPLACE INTO config_checksums (file_path, checksum, checked_at) VALUES (?, ?, ?)",
            (file_path, checksum, now),
        )
        await self._db.commit()

    async def get_checksum(self, file_path: str) -> str | None:
        cursor = await self._db.execute(
            "SELECT checksum FROM config_checksums WHERE file_path = ?", (file_path,)
        )
        row = await cursor.fetchone()
        return row["checksum"] if row else None

    # --- Generated Goals ---

    async def log_goal(self, title: str, priority: int, description: str, reasoning: str, source: str, context: dict | None = None, task_id: int | None = None, status: str = "proposed") -> int:
        now = time.time()
        cursor = await self._db.execute(
            """INSERT INTO generated_goals (timestamp, title, priority, description, reasoning, source, task_id, context, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (now, title, priority, description, reasoning, source, task_id, json.dumps(context) if context else None, status),
        )
        await self._db.commit()
        return cursor.lastrowid

    async def update_goal_status(self, goal_id: int, status: str, task_id: int | None = None):
        if task_id is not None:
            await self._db.execute(
                "UPDATE generated_goals SET status = ?, task_id = ? WHERE id = ?", (status, task_id, goal_id)
            )
        else:
            await self._db.execute(
                "UPDATE generated_goals SET status = ? WHERE id = ?", (status, goal_id)
            )
        await self._db.commit()

    async def get_recent_goals(self, limit: int = 30) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT * FROM generated_goals ORDER BY timestamp DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            if d.get("context") and isinstance(d["context"], str):
                d["context"] = json.loads(d["context"])
            results.append(d)
        return results
