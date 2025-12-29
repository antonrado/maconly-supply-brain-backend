from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.schemas.demand import DemandResult
from app.services.demand_engine import compute_demand, OBSERVATION_WINDOW_DAYS
from tests.test_utils import (
    add_wb_sales,
    add_wb_stock,
    create_article,
    create_article_planning_settings,
    create_global_planning_settings,
    create_wb_mapping,
)


@pytest.mark.usefixtures("db_session")
class TestComputeDemand:
    def test_article_without_wb_mapping_has_zero_demand(self, db_session):
        """Article without WB mapping should yield zero demand and 9999 coverage."""
        article = create_article(db_session, code="A-no-mapping")

        target_date = date(2025, 1, 31)

        result: DemandResult = compute_demand(
            db=db_session,
            article_id=article.id,
            target_date=target_date,
        )

        assert result.deficit == 0
        assert result.avg_daily_sales == 0.0
        assert result.current_stock == 0
        assert result.coverage_days == pytest.approx(9999.0)
        assert "No WB SKU mappings" in (result.explanation or "")
        assert "No WB sales in the last" in (result.explanation or "")

    def test_article_with_mapping_and_stock_but_no_sales(self, db_session):
        """Mapping + stock but no sales -> avg_daily_sales=0, deficit=0, coverage=9999."""
        article = create_article(db_session, code="A-stock-no-sales")
        wb_sku = "SKU-stock-only"
        create_wb_mapping(db_session, article=article, wb_sku=wb_sku)
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=100)

        target_date = date(2025, 1, 31)

        result = compute_demand(db_session, article.id, target_date)

        assert result.avg_daily_sales == 0.0
        assert result.current_stock == 100
        assert result.deficit == 0
        assert result.coverage_days == pytest.approx(9999.0)
        assert "No WB sales in the last" in (result.explanation or "")
        assert "No WB SKU mappings" not in (result.explanation or "")

    def test_short_history_less_than_observation_window(self, db_session):
        """When history is shorter than OBSERVATION_WINDOW_DAYS, avg is over days with sales."""
        article = create_article(db_session, code="A-short-history")
        wb_sku = "SKU-short-history"
        create_wb_mapping(db_session, article=article, wb_sku=wb_sku)

        # Article-specific coverage settings
        create_article_planning_settings(
            db_session,
            article,
            target_coverage_days=20,
        )
        create_global_planning_settings(db_session)

        target_date = date(2025, 1, 31)
        days_with_sales = 10
        total_sales = 0
        for i in range(days_with_sales):
            d = target_date - timedelta(days=i)
            add_wb_sales(db_session, wb_sku=wb_sku, day=d, sales_qty=5)
            total_sales += 5

        result = compute_demand(db_session, article.id, target_date)

        assert result.observation_window_days == OBSERVATION_WINDOW_DAYS
        assert result.forecast_horizon_days == 20
        expected_avg = total_sales / days_with_sales
        assert result.avg_daily_sales == pytest.approx(expected_avg)
        assert f"Sales history is shorter than {OBSERVATION_WINDOW_DAYS} days" in (
            result.explanation or ""
        )

    def test_normal_case_with_article_and_global_settings(self, db_session):
        """Compute demand with both article and global settings and check numeric formulas."""
        article = create_article(db_session, code="A-normal")
        wb_sku = "SKU-normal"
        create_wb_mapping(db_session, article=article, wb_sku=wb_sku)

        # Planning settings
        create_global_planning_settings(
            db_session,
            default_target_coverage_days=60,
        )
        create_article_planning_settings(
            db_session,
            article,
            target_coverage_days=10,
        )

        target_date = date(2025, 1, 31)

        # 5 days of sales: 2, 4, 6, 8, 10 => total 30, avg 6 over 5 days
        sales_per_day = [2, 4, 6, 8, 10]
        total_sales = 0
        for i, qty in enumerate(sales_per_day):
            d = target_date - timedelta(days=i)
            add_wb_sales(db_session, wb_sku=wb_sku, day=d, sales_qty=qty)
            total_sales += qty

        # Stock: 20 units on WB
        add_wb_stock(db_session, wb_sku=wb_sku, stock_qty=20)

        result = compute_demand(db_session, article.id, target_date)

        days_with_sales = len(sales_per_day)
        expected_avg = total_sales / days_with_sales
        expected_forecast_demand = expected_avg * 10  # article-specific target_coverage_days
        expected_deficit = int(max(expected_forecast_demand - 20, 0))
        expected_coverage_days = 20 / expected_avg

        assert result.avg_daily_sales == pytest.approx(expected_avg)
        assert result.forecast_horizon_days == 10
        assert result.forecast_demand == pytest.approx(expected_forecast_demand)
        assert result.current_stock == 20
        assert result.coverage_days == pytest.approx(expected_coverage_days)
        assert result.deficit == expected_deficit
        assert "Using article-specific target_coverage_days" in (result.explanation or "")
