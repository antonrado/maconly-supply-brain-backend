from __future__ import annotations

from pydantic import BaseModel


class WbAccountInfo(BaseModel):
    id: int
    name: str
    supplier_id: str | None
    is_active: bool


class MoySkladAccountInfo(BaseModel):
    id: int
    name: str
    account_id: str | None
    is_active: bool


class IntegrationsConfigSnapshot(BaseModel):
    wb_accounts: list[WbAccountInfo]
    moysklad_accounts: list[MoySkladAccountInfo]
