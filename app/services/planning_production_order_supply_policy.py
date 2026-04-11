from __future__ import annotations

from math import floor


def _in_flight_stage_factor(stage: str | None) -> float:
    stage_key = (stage or "other").strip().lower()
    stage_factors: dict[str, float] = {
        "production": 0.85,
        "china_to_nsk": 0.90,
        "packaging": 0.97,
        "nsk_to_wb": 1.00,
        "other": 0.80,
    }
    return stage_factors.get(stage_key, stage_factors["other"])


def _estimate_effective_in_flight_qty(
    qty: int,
    eta_days: int,
    lead_time_days_total: int,
    stage: str | None,
) -> int:
    if qty <= 0:
        return 0

    eta = max(int(eta_days), 0)
    lead_time = max(int(lead_time_days_total), 0)

    if lead_time > 0 and eta > lead_time:
        return 0

    if lead_time <= 0:
        eta_factor = 1.0
    else:
        eta_factor = (lead_time - eta + 1) / (lead_time + 1)
        eta_factor = max(min(eta_factor, 1.0), 0.0)

    stage_factor = _in_flight_stage_factor(stage)
    effective = floor(qty * eta_factor * stage_factor)
    return max(int(effective), 0)


def _compute_economic_buffer_days(
    *,
    risk_level: str,
    allow_order_with_buffer: bool,
    total_daily_sales: float,
    lead_time_days_total: int,
    days_of_cover_estimate: float,
    ceil_to_int,
) -> int:
    if not allow_order_with_buffer or total_daily_sales <= 0:
        return 0

    if risk_level not in {"critical", "warning"}:
        return 0

    cover_gap_days = max(float(lead_time_days_total) - max(days_of_cover_estimate, 0.0), 0.0)
    if cover_gap_days <= 0:
        return 0

    buffer_days = ceil_to_int(cover_gap_days * 0.35)
    if risk_level == "critical":
        buffer_days += 2
    else:
        buffer_days += 1

    return max(min(buffer_days, 14), 0)
