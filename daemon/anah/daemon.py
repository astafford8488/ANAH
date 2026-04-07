"""Core daemon loop with hierarchical gating."""

import asyncio
import logging
import time

from dotenv import load_dotenv
load_dotenv(override=True)

from anah.config import AnahConfig
from anah.db import Database
from anah.task_queue import TaskQueue
from anah.executor import TaskExecutor
from anah.hermes_bridge import HermesConfig
from anah.checks import l1_survival, l2_state, l3_ecosystem, l4_performance, l5_goal_generation

logger = logging.getLogger("anah.daemon")

L4_CHECK_INTERVAL = 120  # Production: 2min
L5_IDLE_CHECK_INTERVAL = 60  # Production: 60s
L5_COOLDOWN = 180  # Production: 3min


class AnahDaemon:
    def __init__(self, config: AnahConfig):
        self.config = config
        self.db = Database(config.daemon.db_path)
        self.queue: TaskQueue | None = None
        self.executor: TaskExecutor | None = None
        self.running = False
        self._level_status: dict[int, str] = {1: "unknown", 2: "unknown", 3: "unknown", 4: "unknown", 5: "unknown"}
        self._last_l5_run: float = 0

    async def start(self):
        logger.info("ANAH Daemon starting...")
        await self.db.connect()
        self.queue = TaskQueue(self.db)

        # Build Hermes config from main config
        hermes_cfg = None
        if hasattr(self.config, 'hermes'):
            h = self.config.hermes
            hermes_cfg = HermesConfig(
                enabled=h.enabled, mode=h.mode, api_url=h.api_url,
                api_key=h.api_key, model=h.model, hermes_path=h.hermes_path,
                timeout=h.timeout, task_types=h.task_types,
            )

        # Build approval gate config
        approval_cfg = None
        if hasattr(self.config, 'approval_gate'):
            approval_cfg = self.config.approval_gate.model_dump()

        self.executor = TaskExecutor(
            self.db, self.queue,
            hermes_config=hermes_cfg,
            approval_config=approval_cfg,
        )
        self.running = True

        await self.db.log_action(None, "lifecycle", "Daemon started (Phase 3 — Full Loop)", "completed")
        logger.info("Database connected. Task queue initialized. L5 engine ready. Entering main loop.")

        # Seed a startup health report task
        await self.queue.enqueue(
            title="health_report: startup diagnostic",
            source="system",
            description="Automatic health report on daemon startup",
            priority=5,
        )

        # Run check loops + executor + L5 concurrently
        await asyncio.gather(
            self._l1_loop(),
            self._l2_loop(),
            self._l3_loop(),
            self._l4_loop(),
            self._l5_loop(),
            self.executor.start(),
            self._periodic_task_spawner(),
        )

    async def stop(self):
        logger.info("ANAH Daemon stopping...")
        self.running = False
        if self.executor:
            await self.executor.stop()
        await self.db.log_action(None, "lifecycle", "Daemon stopped", "completed")
        await self.db.close()

    def _is_level_healthy(self, level: int) -> bool:
        """Check if a given level is healthy (gates higher levels)."""
        return self._level_status.get(level, "unknown") == "healthy"

    async def _run_checks_and_update(self, level: int, results: list) -> str:
        """Process check results, log them, and determine level status."""
        all_passed = True
        for result in results:
            await self.db.log_check(
                level=level,
                check_name=result.name,
                passed=result.passed,
                duration_ms=result.duration_ms,
                message=result.message,
                details=result.details,
            )
            if not result.passed:
                all_passed = False
                logger.warning(f"L{level} FAIL: {result.name} — {result.message}")
            else:
                logger.debug(f"L{level} OK: {result.name} — {result.message}")

        status = "healthy" if all_passed else "degraded"
        self._level_status[level] = status
        await self.db.update_level_status(level, status, {
            "checks": [{"name": r.name, "passed": r.passed, "message": r.message} for r in results]
        })
        return status

    async def _l1_loop(self):
        """L1 heartbeat loop — runs every 30-60s."""
        interval = self.config.intervals.l1_heartbeat_sec
        thresholds = self.config.thresholds.model_dump()

        while self.running:
            start = time.monotonic()
            action_id = await self.db.log_action(1, "check", "L1 health check cycle")

            try:
                results = await l1_survival.run_all(thresholds)
                status = await self._run_checks_and_update(1, results)
                duration = (time.monotonic() - start) * 1000
                await self.db.complete_action(action_id, "completed", duration)

                if status == "healthy":
                    logger.info(f"L1 ✓ healthy ({duration:.0f}ms)")
                else:
                    logger.warning(f"L1 ✗ degraded ({duration:.0f}ms)")
            except Exception as e:
                self._level_status[1] = "critical"
                await self.db.update_level_status(1, "critical", {"error": str(e)})
                await self.db.complete_action(action_id, "failed")
                logger.error(f"L1 check cycle error: {e}")

            await asyncio.sleep(interval)

    async def _l2_loop(self):
        """L2 state safety loop — runs every 5-10min, gated by L1."""
        interval = self.config.intervals.l2_check_sec

        while self.running:
            if not self._is_level_healthy(1):
                logger.warning("L2 suspended — L1 not healthy")
                await self.db.update_level_status(2, "suspended", {"reason": "L1 not healthy"})
                self._level_status[2] = "suspended"
                await asyncio.sleep(interval)
                continue

            start = time.monotonic()
            action_id = await self.db.log_action(2, "check", "L2 state safety check cycle")

            try:
                results = await l2_state.run_all(
                    self.db,
                    db_path=self.config.daemon.db_path,
                    config_path="config.json",
                )
                status = await self._run_checks_and_update(2, results)
                duration = (time.monotonic() - start) * 1000
                await self.db.complete_action(action_id, "completed", duration)
                logger.info(f"L2 {'✓' if status == 'healthy' else '✗'} {status} ({duration:.0f}ms)")
            except Exception as e:
                self._level_status[2] = "critical"
                await self.db.update_level_status(2, "critical", {"error": str(e)})
                await self.db.complete_action(action_id, "failed")
                logger.error(f"L2 check cycle error: {e}")

            await asyncio.sleep(interval)

    async def _l3_loop(self):
        """L3 ecosystem health loop — runs every 15-30min, gated by L1+L2."""
        interval = self.config.intervals.l3_check_sec

        while self.running:
            if not self._is_level_healthy(1):
                logger.warning("L3 suspended — L1 not healthy")
                self._level_status[3] = "suspended"
                await self.db.update_level_status(3, "suspended", {"reason": "L1 not healthy"})
                await asyncio.sleep(interval)
                continue
            if not self._is_level_healthy(2):
                logger.warning("L3 suspended — L2 not healthy")
                self._level_status[3] = "suspended"
                await self.db.update_level_status(3, "suspended", {"reason": "L2 not healthy"})
                await asyncio.sleep(interval)
                continue

            start = time.monotonic()
            action_id = await self.db.log_action(3, "check", "L3 ecosystem health check cycle")

            try:
                integrations = [i.model_dump() for i in self.config.integrations]
                results = await l3_ecosystem.run_all(
                    integrations=integrations,
                    timeout=self.config.thresholds.api_ping_timeout_sec,
                )
                status = await self._run_checks_and_update(3, results)
                duration = (time.monotonic() - start) * 1000
                await self.db.complete_action(action_id, "completed", duration)
                logger.info(f"L3 {'✓' if status == 'healthy' else '✗'} {status} ({duration:.0f}ms)")
            except Exception as e:
                self._level_status[3] = "critical"
                await self.db.update_level_status(3, "critical", {"error": str(e)})
                await self.db.complete_action(action_id, "failed")
                logger.error(f"L3 check cycle error: {e}")

            await asyncio.sleep(interval)

    async def _l4_loop(self):
        """L4 performance & impact loop — runs every 2min, gated by L1+L2+L3."""
        interval = L4_CHECK_INTERVAL

        while self.running:
            # Gate on lower levels
            gated = False
            for gate_level in (1, 2, 3):
                if not self._is_level_healthy(gate_level):
                    logger.warning(f"L4 suspended — L{gate_level} not healthy")
                    self._level_status[4] = "suspended"
                    await self.db.update_level_status(4, "suspended", {"reason": f"L{gate_level} not healthy"})
                    gated = True
                    break

            if not gated:
                start = time.monotonic()
                action_id = await self.db.log_action(4, "check", "L4 performance check cycle")

                try:
                    results = await l4_performance.run_all(self.db, self.queue)
                    status = await self._run_checks_and_update(4, results)
                    duration = (time.monotonic() - start) * 1000
                    await self.db.complete_action(action_id, "completed", duration)
                    logger.info(f"L4 {'✓' if status == 'healthy' else '✗'} {status} ({duration:.0f}ms)")
                except Exception as e:
                    self._level_status[4] = "critical"
                    await self.db.update_level_status(4, "critical", {"error": str(e)})
                    await self.db.complete_action(action_id, "failed")
                    logger.error(f"L4 check cycle error: {e}")

            await asyncio.sleep(interval)

    async def _l5_loop(self):
        """L5 goal generation loop — triggered when queue is idle, gated by L1-L4."""
        # Wait for lower levels to stabilize
        await asyncio.sleep(45)

        while self.running:
            # Gate on all lower levels
            gated = False
            for gate_level in (1, 2, 3, 4):
                if not self._is_level_healthy(gate_level):
                    self._level_status[5] = "suspended"
                    await self.db.update_level_status(5, "suspended", {"reason": f"L{gate_level} not healthy"})
                    gated = True
                    break

            if not gated:
                # Check cooldown
                elapsed_since_last = time.time() - self._last_l5_run
                if elapsed_since_last < L5_COOLDOWN:
                    await asyncio.sleep(L5_IDLE_CHECK_INTERVAL)
                    continue

                # Check if queue is idle (trigger condition)
                stats = await self.queue.get_stats()
                queue_idle = stats["queued"] == 0 and stats["running"] == 0

                if queue_idle:
                    start = time.monotonic()
                    action_id = await self.db.log_action(5, "goal", "L5 goal generation cycle")
                    self._last_l5_run = time.time()

                    try:
                        # Run L5 status check
                        check_result = await l5_goal_generation.run_check(self.db, self.queue)
                        await self.db.log_check(
                            level=5, check_name=check_result.name, passed=check_result.passed,
                            duration_ms=check_result.duration_ms, message=check_result.message,
                            details=check_result.details,
                        )

                        # Generate goals
                        goals, context = await l5_goal_generation.run_goal_generation(self.db, self.queue)

                        enacted_count = 0
                        for goal in goals:
                            goal_id = await self.db.log_goal(
                                title=goal.title, priority=goal.priority,
                                description=goal.description, reasoning=goal.reasoning,
                                source=goal.source, context=context,
                            )
                            task_id = await self.queue.enqueue(
                                title=goal.title,
                                source="l5_generated",
                                description=f"{goal.description} | Reasoning: {goal.reasoning}",
                                priority=goal.priority,
                            )
                            await self.db.update_goal_status(goal_id, "enacted", task_id)
                            enacted_count += 1
                            logger.info(f"L5 goal enacted: {goal.title} (P{goal.priority}, via {goal.source})")

                        self._level_status[5] = "healthy"
                        await self.db.update_level_status(5, "healthy", {
                            "checks": [{"name": "goal_generation", "passed": True, "message": f"Generated {enacted_count} goals"}],
                            "goals_generated": enacted_count,
                            "source": goals[0].source if goals else "none",
                        })

                        duration = (time.monotonic() - start) * 1000
                        await self.db.complete_action(action_id, "completed", duration)
                        logger.info(f"L5 ✓ generated {enacted_count} goals ({duration:.0f}ms)")

                    except Exception as e:
                        self._level_status[5] = "critical"
                        await self.db.update_level_status(5, "critical", {"error": str(e)})
                        await self.db.complete_action(action_id, "failed")
                        logger.error(f"L5 goal generation error: {e}")

            await asyncio.sleep(L5_IDLE_CHECK_INTERVAL)

    async def _periodic_task_spawner(self):
        """Spawn recurring system tasks (cleanup, health reports)."""
        await asyncio.sleep(30)

        cycle = 0
        while self.running:
            cycle += 1

            if cycle % 10 == 0:
                await self.queue.enqueue(
                    title="self_diagnostic: periodic system check",
                    source="system",
                    description="Periodic full-system diagnostic",
                    priority=3,
                )

            if cycle % 30 == 0:
                await self.queue.enqueue(
                    title="health_report: hourly summary",
                    source="system",
                    description="Hourly health and performance summary",
                    priority=2,
                )

            if cycle % 60 == 0:
                await self.queue.enqueue(
                    title="cleanup: log retention",
                    source="system",
                    description="Prune old logs beyond 7-day retention",
                    priority=1,
                )

            await asyncio.sleep(L4_CHECK_INTERVAL)
