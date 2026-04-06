"""L2 — Persistent State Safety checks.

Every 5-10 min. File I/O only, no LLM.
Checksums, DB integrity, backup verification.
"""

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from anah.db import Database


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: dict | None = None


def _sha256(file_path: str) -> str:
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


async def check_config_integrity(db: Database, config_path: str = "config.json") -> CheckResult:
    """Verify config file hasn't been corrupted since last write."""
    start = time.monotonic()
    try:
        if not os.path.exists(config_path):
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult("config_integrity", False, elapsed, f"Config file missing: {config_path}")

        current_hash = _sha256(config_path)
        stored_hash = await db.get_checksum(config_path)

        if stored_hash is None:
            # First run — store the checksum
            await db.set_checksum(config_path, current_hash)
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult("config_integrity", True, elapsed, "Initial checksum stored", {"checksum": current_hash})

        elapsed = (time.monotonic() - start) * 1000
        if current_hash == stored_hash:
            return CheckResult("config_integrity", True, elapsed, "Config integrity OK", {"checksum": current_hash})

        # Config changed — update checksum but flag it
        await db.set_checksum(config_path, current_hash)
        return CheckResult("config_integrity", True, elapsed, "Config changed (checksum updated)", {
            "old_checksum": stored_hash, "new_checksum": current_hash
        })
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("config_integrity", False, elapsed, f"Config check failed: {e}")


async def check_db_integrity(db_path: str = "anah.db") -> CheckResult:
    """SQLite integrity check on the state database."""
    start = time.monotonic()
    try:
        import aiosqlite
        async with aiosqlite.connect(db_path) as conn:
            cursor = await conn.execute("PRAGMA integrity_check")
            result = await cursor.fetchone()
            elapsed = (time.monotonic() - start) * 1000
            if result[0] == "ok":
                return CheckResult("db_integrity", True, elapsed, "Database integrity OK")
            return CheckResult("db_integrity", False, elapsed, f"DB integrity issue: {result[0]}")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("db_integrity", False, elapsed, f"DB integrity check failed: {e}")


async def check_backup_recency(db_path: str = "anah.db", max_age_sec: int = 900) -> CheckResult:
    """Verify backup exists and is recent enough."""
    start = time.monotonic()
    backup_path = db_path + ".backup"
    try:
        if not os.path.exists(backup_path):
            # Create initial backup
            shutil.copy2(db_path, backup_path)
            elapsed = (time.monotonic() - start) * 1000
            return CheckResult("backup_recency", True, elapsed, "Initial backup created")

        age = time.time() - os.path.getmtime(backup_path)
        elapsed = (time.monotonic() - start) * 1000
        if age < max_age_sec:
            return CheckResult("backup_recency", True, elapsed, f"Backup age: {age:.0f}s", {"age_sec": age})

        return CheckResult("backup_recency", False, elapsed, f"Backup stale: {age:.0f}s > {max_age_sec}s", {"age_sec": age})
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("backup_recency", False, elapsed, f"Backup check failed: {e}")


async def perform_backup(db_path: str = "anah.db") -> CheckResult:
    """Create a fresh backup of the state database."""
    start = time.monotonic()
    backup_path = db_path + ".backup"
    try:
        shutil.copy2(db_path, backup_path)
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("perform_backup", True, elapsed, "Backup completed")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("perform_backup", False, elapsed, f"Backup failed: {e}")


async def run_all(db: Database, db_path: str = "anah.db", config_path: str = "config.json") -> list[CheckResult]:
    """Run all L2 checks."""
    results = []
    results.append(await check_config_integrity(db, config_path))
    results.append(await check_db_integrity(db_path))

    backup_result = await check_backup_recency(db_path)
    results.append(backup_result)

    # Auto-repair: if backup is stale, create a new one
    if not backup_result.passed:
        results.append(await perform_backup(db_path))

    return results
