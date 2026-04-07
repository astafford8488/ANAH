"""Configuration loader for ANAH daemon."""

import json
from pathlib import Path
from pydantic import BaseModel


class IntervalsConfig(BaseModel):
    l1_heartbeat_sec: int = 30
    l2_check_sec: int = 300
    l3_check_sec: int = 900


class ThresholdsConfig(BaseModel):
    cpu_percent_max: int = 90
    ram_percent_max: int = 85
    disk_percent_max: int = 90
    dns_timeout_sec: int = 5
    api_ping_timeout_sec: int = 10


class DaemonConfig(BaseModel):
    db_path: str = "anah.db"
    log_level: str = "INFO"


class IntegrationEndpoint(BaseModel):
    name: str
    url: str
    method: str = "GET"
    expected_status: int = 200


class NotificationsConfig(BaseModel):
    enabled: bool = False
    webhook_url: str | None = None


class HermesConfig(BaseModel):
    enabled: bool = False
    mode: str = "api"  # "api" or "rpc"
    api_url: str = "http://localhost:11434/v1"
    api_key: str = ""
    model: str = "hermes"
    hermes_path: str = "hermes"
    timeout: int = 120
    task_types: list[str] = ["hermes"]


class ApprovalGateConfig(BaseModel):
    enabled: bool = True
    require_approval: list[str] = ["hermes"]  # Task types needing human approval
    auto_approve: list[str] = ["health_report", "self_diagnostic", "cleanup", "echo"]  # Always auto-approved


class AnahConfig(BaseModel):
    daemon: DaemonConfig = DaemonConfig()
    intervals: IntervalsConfig = IntervalsConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    integrations: list[IntegrationEndpoint] = []
    notifications: NotificationsConfig = NotificationsConfig()
    hermes: HermesConfig = HermesConfig()
    approval_gate: ApprovalGateConfig = ApprovalGateConfig()


def load_config(config_path: str = "config.json") -> AnahConfig:
    path = Path(config_path)
    if path.exists():
        data = json.loads(path.read_text())
        return AnahConfig(**data)
    return AnahConfig()
