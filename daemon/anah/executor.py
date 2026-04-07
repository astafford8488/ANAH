"""Task Executor — async worker that pulls tasks from the queue and executes them.

Tasks are Python callables registered by name. The executor runs a continuous loop,
pulling the next highest-priority task and dispatching it to the registered handler.

Supports:
- Built-in task handlers (health_report, self_diagnostic, cleanup, echo)
- Hermes Agent delegation for "hermes:" prefixed tasks
- Human approval gate: configurable per-task-type hold before execution
"""

import asyncio
import logging
import time
import traceback
from typing import Callable, Awaitable

from anah.db import Database
from anah.task_queue import TaskQueue
from anah.hermes_bridge import HermesBridge, HermesConfig

logger = logging.getLogger("anah.executor")

# Type for task handlers: async functions that receive task dict and return a result dict
TaskHandler = Callable[[dict], Awaitable[dict | None]]


class TaskExecutor:
    def __init__(
        self,
        db: Database,
        queue: TaskQueue,
        poll_interval: float = 5.0,
        hermes_config: HermesConfig | None = None,
        approval_config: dict | None = None,
    ):
        self.db = db
        self.queue = queue
        self.poll_interval = poll_interval
        self.running = False
        self._handlers: dict[str, TaskHandler] = {}
        self._current_task: dict | None = None

        # Hermes Agent bridge
        self.hermes = HermesBridge(hermes_config or HermesConfig())
        self._hermes_task_types = set(
            (hermes_config.task_types if hermes_config else [])
        )

        # Approval gate config
        self._approval_enabled = False
        self._require_approval: set[str] = set()
        self._auto_approve: set[str] = set()
        if approval_config:
            self._approval_enabled = approval_config.get("enabled", False)
            self._require_approval = set(approval_config.get("require_approval", []))
            self._auto_approve = set(approval_config.get("auto_approve", []))

        # Register built-in task types
        self._register_builtins()

    def register(self, task_type: str, handler: TaskHandler):
        """Register a handler for a task type."""
        self._handlers[task_type] = handler
        logger.info(f"Registered task handler: {task_type}")

    def _register_builtins(self):
        """Register built-in task handlers."""
        self.register("health_report", self._handle_health_report)
        self.register("self_diagnostic", self._handle_self_diagnostic)
        self.register("cleanup", self._handle_cleanup)
        self.register("echo", self._handle_echo)
        self.register("hermes", self._handle_hermes)

    async def start(self):
        """Start the executor loop."""
        self.running = True
        logger.info("Task Executor started")
        await self.db.log_action(None, "lifecycle", "Task Executor started", "completed")

        while self.running:
            task = await self.queue.dequeue()
            if task is None:
                await asyncio.sleep(self.poll_interval)
                continue

            await self._execute_task(task)

    async def stop(self):
        self.running = False
        logger.info("Task Executor stopping")

    def _needs_approval(self, task_type: str) -> bool:
        """Check if a task type requires human approval before execution."""
        if not self._approval_enabled:
            return False
        if task_type in self._auto_approve:
            return False
        if task_type in self._require_approval:
            return True
        # Default: tasks not in either list are auto-approved
        return False

    async def _execute_task(self, task: dict):
        """Execute a single task."""
        task_id = task["id"]
        title = task["title"]
        self._current_task = task

        # Determine task type from title prefix or source
        task_type = self._resolve_task_type(task)

        # Approval gate check — skip if already approved
        already_approved = False
        if task.get("result"):
            result_data = task["result"]
            if isinstance(result_data, str):
                import json
                try:
                    result_data = json.loads(result_data)
                except Exception:
                    result_data = {}
            already_approved = isinstance(result_data, dict) and result_data.get("approved", False)

        if self._needs_approval(task_type) and not already_approved:
            logger.info(f"Task {task_id} requires approval: {title} (type={task_type})")
            # Move back from running to pending_approval
            await self.queue.hold_for_approval(task_id)
            await self.db.log_action(
                level=None, action_type="approval",
                description=f"Awaiting approval: {title}",
                status="completed",
                details={"task_id": task_id, "task_type": task_type},
            )
            self._current_task = None
            return

        handler = self._handlers.get(task_type)

        action_id = await self.db.log_action(
            level=4, action_type="task_exec",
            description=f"Executing: {title}",
            status="started",
            details={"task_id": task_id, "task_type": task_type},
        )

        start = time.monotonic()
        try:
            if handler:
                result = await handler(task)
            else:
                # Default: just mark it done (for manual/generic tasks)
                result = {"status": "completed", "note": f"No handler for type '{task_type}', auto-completed"}
                logger.warning(f"No handler for task type '{task_type}', auto-completing task {task_id}")

            duration = (time.monotonic() - start) * 1000
            await self.queue.complete(task_id, result)
            await self.db.complete_action(action_id, "completed", duration)
            logger.info(f"Task {task_id} completed: {title} ({duration:.0f}ms)")

        except Exception as e:
            duration = (time.monotonic() - start) * 1000
            error_msg = f"{type(e).__name__}: {e}"
            await self.queue.fail(task_id, error_msg)
            await self.db.complete_action(action_id, "failed", duration)
            logger.error(f"Task {task_id} failed: {title} — {error_msg}")
            logger.debug(traceback.format_exc())

        finally:
            self._current_task = None

    def _resolve_task_type(self, task: dict) -> str:
        """Resolve task type from task metadata."""
        # Check if title starts with a known type prefix
        title_lower = task["title"].lower()
        for registered_type in self._handlers:
            if title_lower.startswith(registered_type):
                return registered_type

        # Check source for hints
        if task.get("source") == "repair":
            return "self_diagnostic"

        # Check description/result for type hints
        result = task.get("result")
        if isinstance(result, dict) and "task_type" in result:
            return result["task_type"]

        return "generic"

    # --- Built-in task handlers ---

    async def _handle_health_report(self, task: dict) -> dict:
        """Generate a health report from recent check data."""
        hierarchy = await self.db.get_hierarchy()
        recent_logs = await self.db.get_recent_logs(limit=50)
        queue_stats = await self.queue.get_stats()

        total = len(recent_logs)
        passed = sum(1 for l in recent_logs if l["passed"])
        levels_healthy = sum(1 for h in hierarchy if h["status"] == "healthy")

        report = {
            "hierarchy_summary": {h["name"]: h["status"] for h in hierarchy},
            "levels_healthy": levels_healthy,
            "levels_total": len(hierarchy),
            "recent_pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
            "queue_stats": queue_stats,
            "generated_at": time.time(),
        }

        await self.db.log_action(
            level=4, action_type="report",
            description=f"Health report: {levels_healthy}/{len(hierarchy)} levels healthy, {report['recent_pass_rate']}% pass rate",
            status="completed",
            details=report,
        )
        return report

    async def _handle_self_diagnostic(self, task: dict) -> dict:
        """Run a full diagnostic across all levels."""
        from anah.checks import l1_survival, l2_state, l3_ecosystem

        results = {}

        # Run L1
        l1 = await l1_survival.run_all()
        results["l1"] = [{"name": r.name, "passed": r.passed, "message": r.message, "ms": r.duration_ms} for r in l1]

        # Run L2
        l2 = await l2_state.run_all(self.db)
        results["l2"] = [{"name": r.name, "passed": r.passed, "message": r.message, "ms": r.duration_ms} for r in l2]

        # Run L3
        l3 = await l3_ecosystem.run_all()
        results["l3"] = [{"name": r.name, "passed": r.passed, "message": r.message, "ms": r.duration_ms} for r in l3]

        all_checks = results["l1"] + results["l2"] + results["l3"]
        total_pass = sum(1 for c in all_checks if c["passed"])

        return {
            "diagnostic": results,
            "total_checks": len(all_checks),
            "total_passed": total_pass,
            "all_healthy": total_pass == len(all_checks),
        }

    async def _handle_cleanup(self, task: dict) -> dict:
        """Cleanup old logs and data beyond retention period."""
        retention_sec = 86400 * 7  # 7 days
        cutoff = time.time() - retention_sec

        cursor = await self.db._db.execute(
            "DELETE FROM health_logs WHERE timestamp < ?", (cutoff,)
        )
        logs_deleted = cursor.rowcount

        cursor = await self.db._db.execute(
            "DELETE FROM agent_actions WHERE timestamp < ?", (cutoff,)
        )
        actions_deleted = cursor.rowcount

        cursor = await self.db._db.execute(
            "DELETE FROM task_queue WHERE status IN ('completed', 'failed') AND completed_at < ?", (cutoff,)
        )
        tasks_deleted = cursor.rowcount

        await self.db._db.commit()

        return {
            "logs_deleted": logs_deleted,
            "actions_deleted": actions_deleted,
            "tasks_deleted": tasks_deleted,
            "retention_days": 7,
        }

    async def _handle_echo(self, task: dict) -> dict:
        """Simple echo task for testing."""
        return {"echo": task["title"], "description": task.get("description", ""), "timestamp": time.time()}

    async def _handle_hermes(self, task: dict) -> dict:
        """Delegate task execution to Hermes Agent."""
        if not self.hermes.is_available:
            return {
                "status": "skipped",
                "note": "Hermes integration is disabled. Enable in config.json under 'hermes.enabled'.",
            }

        logger.info(f"Delegating task {task['id']} to Hermes Agent: {task['title']}")

        result = await self.hermes.execute_task(task)

        if result.success:
            await self.db.log_action(
                level=4, action_type="task_exec",
                description=f"Hermes completed: {task['title']}",
                status="completed",
                details={
                    "task_id": task["id"],
                    "hermes_output": result.output[:500],
                    "tool_calls": len(result.tool_calls),
                },
            )
            return {
                "status": "completed",
                "executor": "hermes",
                "output": result.output,
                "tool_calls": result.tool_calls,
            }
        else:
            raise RuntimeError(f"Hermes execution failed: {result.error}")
