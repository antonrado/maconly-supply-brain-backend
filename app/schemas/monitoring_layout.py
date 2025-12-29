from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel


class MonitoringLayoutTile(BaseModel):
    id: str
    title: str
    description: str
    type: Literal["counter", "timeseries", "table_link"]
    primary_metric: Optional[str] = None
    secondary_metrics: Optional[List[str]] = None
    source_endpoint: str
    source_params: Optional[Dict[str, object]] = None


class MonitoringLayoutSection(BaseModel):
    id: str
    title: str
    description: Optional[str] = None
    tiles: List[MonitoringLayoutTile]


class MonitoringLayoutResponse(BaseModel):
    sections: List[MonitoringLayoutSection]
