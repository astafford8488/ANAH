"""L3 — Task Ecosystem Health checks.

Every 15-30 min. External API pings, integration health.
Exponential backoff on failures. Notifies on unresolvable issues.
"""

import time
from dataclasses import dataclass

import httpx


@dataclass
class CheckResult:
    name: str
    passed: bool
    duration_ms: float
    message: str
    details: dict | None = None


async def check_integration_health(name: str, url: str, method: str = "GET", expected_status: int = 200, timeout: int = 10) -> CheckResult:
    """Ping an integration endpoint."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if method.upper() == "GET":
                resp = await client.get(url)
            elif method.upper() == "POST":
                resp = await client.post(url)
            else:
                resp = await client.request(method.upper(), url)

        elapsed = (time.monotonic() - start) * 1000
        details = {"status_code": resp.status_code, "url": url}

        if resp.status_code == expected_status:
            return CheckResult(f"integration_{name}", True, elapsed, f"{name}: {resp.status_code} OK", details)
        return CheckResult(f"integration_{name}", False, elapsed, f"{name}: expected {expected_status}, got {resp.status_code}", details)
    except httpx.TimeoutException:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult(f"integration_{name}", False, elapsed, f"{name}: timeout after {timeout}s", {"url": url})
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult(f"integration_{name}", False, elapsed, f"{name}: {e}", {"url": url})


async def check_anthropic_api(timeout: int = 10) -> CheckResult:
    """Check Anthropic API is reachable (not authenticated, just connectivity)."""
    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get("https://api.anthropic.com/v1/messages")
        elapsed = (time.monotonic() - start) * 1000
        # 401 is expected without auth — means the API is reachable
        if resp.status_code in (401, 403):
            return CheckResult("anthropic_api", True, elapsed, "Anthropic API reachable", {"status_code": resp.status_code})
        return CheckResult("anthropic_api", True, elapsed, f"Anthropic API responded: {resp.status_code}", {"status_code": resp.status_code})
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        return CheckResult("anthropic_api", False, elapsed, f"Anthropic API unreachable: {e}")


async def run_all(integrations: list[dict] | None = None, timeout: int = 10) -> list[CheckResult]:
    """Run all L3 checks."""
    results = []

    # Always check Anthropic API
    results.append(await check_anthropic_api(timeout))

    # Check configured integrations
    for integration in (integrations or []):
        results.append(await check_integration_health(
            name=integration.get("name", "unknown"),
            url=integration["url"],
            method=integration.get("method", "GET"),
            expected_status=integration.get("expected_status", 200),
            timeout=timeout,
        ))

    return results
