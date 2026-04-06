"""L1 — Operational Survival checks.

Heartbeat every 30-60s. Pure systems checks, no LLM.
Failure here halts all higher-level activity.
"""

import asyncio
import os
import socket
import time
import tempfile
from dataclasses import dataclass

import psutil


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: dict | None = None


async def check_network_connectivity(timeout: int = 5) -> CheckResult:
    """DNS resolution + gateway ping."""
    start = time.monotonic()
    try:
        loop = asyncio.get_event_loop()
        # DNS resolution check
        await asyncio.wait_for(
            loop.run_in_executor(None, socket.getaddrinfo, "dns.google", 443),
            timeout=timeout,
        )
        # TCP connectivity check (more reliable than ICMP on Windows)
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection("8.8.8.8", 53),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()

        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("network_connectivity", True, elapsed, "DNS and network reachable")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("network_connectivity", False, elapsed, f"Network check failed: {e}")


async def check_filesystem_access() -> CheckResult:
    """Verify read/write access to working directory."""
    start = time.monotonic()
    try:
        test_file = os.path.join(tempfile.gettempdir(), ".anah_fs_check")
        with open(test_file, "w") as f:
            f.write("anah_health_check")
        with open(test_file, "r") as f:
            content = f.read()
        os.remove(test_file)

        if content != "anah_health_check":
            raise ValueError("Filesystem read/write mismatch")

        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("filesystem_access", True, elapsed, "Read/write OK")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("filesystem_access", False, elapsed, f"Filesystem check failed: {e}")


async def check_compute_resources(cpu_max: int = 90, ram_max: int = 85, disk_max: int = 90) -> CheckResult:
    """CPU, RAM, and disk usage within thresholds."""
    start = time.monotonic()
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent

        details = {"cpu_percent": cpu, "ram_percent": ram, "disk_percent": disk}
        issues = []
        if cpu > cpu_max:
            issues.append(f"CPU {cpu}% > {cpu_max}%")
        if ram > ram_max:
            issues.append(f"RAM {ram}% > {ram_max}%")
        if disk > disk_max:
            issues.append(f"Disk {disk}% > {disk_max}%")

        elapsed = (time.monotonic() - start) * 1000
        if issues:
            return CheckResult("compute_resources", False, elapsed, "; ".join(issues), details)
        return CheckResult("compute_resources", True, elapsed, f"CPU {cpu}%, RAM {ram}%, Disk {disk}%", details)
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("compute_resources", False, elapsed, f"Compute check failed: {e}")


async def check_wifi_interface() -> CheckResult:
    """Verify at least one active network interface."""
    start = time.monotonic()
    try:
        stats = psutil.net_if_stats()
        active = [name for name, info in stats.items() if info.isup and name != "lo"]
        elapsed = (time.monotonic() - start) * 1000
        if active:
            return CheckResult("wifi_interface", True, elapsed, f"Active interfaces: {', '.join(active)}", {"interfaces": active})
        return CheckResult("wifi_interface", False, elapsed, "No active network interfaces found")
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("wifi_interface", False, elapsed, f"Interface check failed: {e}")


async def run_all(thresholds: dict | None = None) -> list[CheckResult]:
    """Run all L1 checks concurrently."""
    t = thresholds or {}
    results = await asyncio.gather(
        check_network_connectivity(timeout=t.get("dns_timeout_sec", 5)),
        check_filesystem_access(),
        check_compute_resources(
            cpu_max=t.get("cpu_percent_max", 90),
            ram_max=t.get("ram_percent_max", 85),
            disk_max=t.get("disk_percent_max", 90),
        ),
        check_wifi_interface(),
    )
    return list(results)
