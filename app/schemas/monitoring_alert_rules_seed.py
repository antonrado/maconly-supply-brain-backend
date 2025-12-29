from __future__ import annotations

from pydantic import BaseModel


class MonitoringAlertRulesSeedResponse(BaseModel):
    created_ids: list[int]
    skipped_ids: list[int]
