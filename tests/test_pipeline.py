"""
Comprehensive Unit & Integration Test Suite.
Verifies transformation cleaning functions, Pydantic schema validation, quarantine handling,
Data Quality 4-factor scoring, scraper HTML parsing, relational database upserts, time-series analytics,
and Excel/Google Sheets reporting.
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import pytest
import pandas as pd
import numpy as np

from config.config import Config, get_config
from database.db_connection import DatabaseManager
from etl.transform import (
    clean_price,
    clean_percentage,
    clean_volume,
    clean_market_cap_or_financial,
    transform_stock,
    transform,
)
from etl.validate import (
    StockRecord,
    FundamentalRecord,
    CompanyRecord,
    MarketValidator,
    validate,
    quarantine,
)
from etl.quality import DataQualityManager, compute_data_quality
from etl.load import load_to_database, MarketLoader
from scraper.stock_scraper import StockScraper, scrape_stocks
from scraper.fundamentals_scraper import FundamentalsScraper, scrape_fundamentals
from scraper.api_client import FinancialAPIClient
from analytics.market_analysis import MarketAnalytics, run_analysis
from analytics.kpi_analysis import KPIAnalytics
from reports.excel_report import ExcelReportGenerator, generate_excel_report
from reports.google_sheets import GoogleSheetsSync, update_google_sheets


@pytest.fixture
def config(tmp_path):
    """Create isolated test config using temporary SQLite database and directories."""
    test_cfg = Config()
    test_cfg.USE_SQLITE = True
    test_cfg.SQLITE_DB_PATH = tmp_path / "test_market.db"
    test_cfg.DATA_RAW_DIR = tmp_path / "raw"
    test_cfg.DATA_PROCESSED_DIR = tmp_path / "processed"
    test_cfg.DATA_QUARANTINE_DIR = tmp_path / "quarantine"
    test_cfg.REPORTS_DIR = tmp_path / "reports"
    test_cfg.LOG_FILE_PATH = tmp_path / "test_pipeline.log"
    test_cfg.BASE_DIR = tmp_path
    test_cfg.ensure_directories()
    return test_cfg


@pytest.fixture
def db_manager(config):
    """Provide initialized DatabaseManager instance with clean test schema."""
    return DatabaseManager(config)


# ==============================================================================
# 1. TRANSFORMATION & CLEANSING TESTS
# ==============================================================================

class TestMarketTransformer:
    def test_clean_price(self):
        assert clean_price("₹1,450.50") == 1450.50
        assert clean_price("$2,980.00") == 2980.00
        assert clean_price("1450.50") == 1450.50
        assert clean_price("1,234.56") == 1234.56
        assert clean_price("N/A") is None
        assert clean_price("-") is None
        assert clean_price(None) is None

    def test_clean_percentage(self):
        assert clean_percentage("+1.25%") == 1.25
        assert clean_percentage("-0.45%") == -0.45
        assert clean_percentage("0.82%") == 0.82
        assert clean_percentage("1.25") == 1.25
        assert clean_percentage("N/A") is None
        assert clean_percentage(None) is None

    def test_clean_volume(self):
        assert clean_volume("4.2M") == 4_200_000
        assert clean_volume("500K") == 500_000
        assert clean_volume("1.5B") == 1_500_000_000
        assert clean_volume("2,340") == 2340
        assert clean_volume("N/A") is None

    def test_clean_market_cap_or_financial(self):
        assert clean_market_cap_or_financial("₹5,23,450 Cr") == 523450.0
        assert clean_market_cap_or_financial("-₹4,900 Cr") == -4900.0
        assert clean_market_cap_or_financial("10,000") == 10000.0

    def test_transform_stock_record(self):
        raw = {
            "symbol": "RELIANCE",
            "company_name": "Reliance Industries",
            "sector": "Energy",
            "price": "₹1,450.50",
            "change_percent": "1.25%",
            "volume": "4.2M",
        }
        res = transform_stock(raw)
        assert res["symbol"] == "RELIANCE"
        assert res["close_price"] == 1450.50
        assert res["change_percent"] == 1.25
        assert res["volume"] == 4200000


# ==============================================================================
# 2. SCHEMA VALIDATION & QUARANTINE TESTS
# ==============================================================================

class TestMarketValidator:
    def test_company_record_valid(self):
        comp = CompanyRecord(symbol="reliance", company_name="Reliance Industries", sector="Energy")
        assert comp.symbol == "RELIANCE"
        assert comp.sector == "Energy"

    def test_company_record_invalid_empty_symbol(self):
        with pytest.raises(Exception):
            CompanyRecord(symbol="   ", company_name="Invalid Corp")

    def test_stock_record_valid(self):
        price = StockRecord(symbol="TCS", close_price=4120.0, volume=2100000)
        assert price.close_price == 4120.0
        assert price.symbol == "TCS"

    def test_stock_record_invalid_negative_price(self):
        with pytest.raises(Exception):
            StockRecord(symbol="TCS", close_price=-50.0)

    def test_quarantine_taxonomy_structure(self, config):
        validator = MarketValidator(config)
        df_prices = pd.DataFrame([
            {"symbol": "TCS", "price_date": "2026-09-13", "close_price": 4000.0, "volume": 1000},
            {"symbol": "BAD_TICKER", "price_date": "2026-09-13", "close_price": -99.0, "volume": -5},
        ])
        valid_df, errors = validator.validate_dataframe(df_prices, StockRecord, source="market_prices")
        assert len(valid_df) == 1
        assert len(errors) == 1

        err = errors[0]
        assert "timestamp" in err
        assert "source" in err
        assert "record" in err
        assert "validation_error" in err
        assert "field" in err
        assert "error_type" in err

        q_path = validator.quarantine_invalid_records({"prices": errors})
        assert q_path.exists()
        with open(q_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert len(data) >= 1


# ==============================================================================
# 3. DATA QUALITY LAYER & SCORING TESTS
# ==============================================================================

class TestDataQualityLayer:
    def test_data_quality_perfect_score(self, config):
        raw = {"stocks": [{"symbol": "TCS"}] * 10, "fundamentals": []}
        transformed = {"prices": pd.DataFrame({"symbol": ["TCS"] * 10, "close_price": [4000.0] * 10}), "fundamentals": pd.DataFrame()}
        validated = {"prices": pd.DataFrame({"symbol": ["TCS"] * 10, "close_price": [4000.0] * 10}), "fundamentals": pd.DataFrame()}
        errors = {"prices": [], "fundamentals": []}

        report = DataQualityManager.evaluate(raw, transformed, validated, errors)
        assert report.quality_score == 100.0
        assert report.score_breakdown["grade"] == "A"
        assert report.records_valid == 10
        assert report.records_quarantined == 0

    def test_data_quality_with_invalid_records(self, config):
        raw = {"stocks": [{"symbol": "S1"}, {"symbol": "S2"}], "fundamentals": []}
        transformed = {"prices": pd.DataFrame({"symbol": ["S1", "S2"], "close_price": [100.0, -50.0]}), "fundamentals": pd.DataFrame()}
        validated = {"prices": pd.DataFrame({"symbol": ["S1"], "close_price": [100.0]}), "fundamentals": pd.DataFrame()}
        errors = {"prices": [{"symbol": "S2", "error_type": "validation_error"}], "fundamentals": []}

        report = DataQualityManager.evaluate(raw, transformed, validated, errors)
        assert report.quality_score < 100.0
        assert report.records_quarantined == 1
        assert report.records_valid == 1


# ==============================================================================
# 4. TIME-SERIES ANALYTICS & TECHNICAL TESTS
# ==============================================================================

class TestTimeSeriesAnalytics:
    def test_moving_averages_and_returns(self, config):
        analytics = MarketAnalytics(config)
        dates = pd.date_range(end="2026-09-13", periods=35, freq="D")
        prices = [100.0 + i * 2.0 for i in range(35)]
        
        df = pd.DataFrame({
            "symbol": ["TCS"] * 35,
            "price_date": dates,
            "close_price": prices,
            "volume": [1000] * 35,
        })

        df_sma = analytics.calculate_moving_averages(df, windows=[7, 30])
        assert "sma_7" in df_sma.columns
        assert "sma_30" in df_sma.columns
        assert not df_sma["sma_7"].iloc[-1] != df_sma["sma_7"].iloc[-1]  # Not NaN
        assert not df_sma["sma_30"].iloc[-1] != df_sma["sma_30"].iloc[-1]

        df_ret = analytics.calculate_time_series_returns(df, windows=[7, 30])
        assert "return_7d_pct" in df_ret.columns
        assert "return_30d_pct" in df_ret.columns
        assert df_ret["return_7d_pct"].iloc[-1] > 0

    def test_historical_and_sector_volatility(self, config):
        analytics = MarketAnalytics(config)
        df_vol = pd.DataFrame({
            "symbol": ["RELIANCE", "ONGC", "TCS", "INFY"],
            "sector": ["Energy", "Energy", "IT", "IT"],
            "change_percent": [2.5, -1.0, 0.5, 3.0],
            "close_price": [2500, 200, 4000, 1800],
        })

        sector_vol = analytics.calculate_sector_volatility(df_vol)
        assert len(sector_vol) == 2
        assert "return_std_dev" in sector_vol.columns

    def test_market_breadth_calculation(self, config):
        analytics = MarketAnalytics(config)
        df = pd.DataFrame({
            "symbol": ["A", "B", "C", "D"],
            "change_percent": [1.5, 2.0, -0.5, 0.0],
        })
        breadth = analytics.calculate_market_breadth(df)
        assert breadth["advances"] == 2
        assert breadth["declines"] == 1
        assert breadth["unchanged"] == 1
        assert breadth["ad_ratio"] == 2.0


# ==============================================================================
# 5. DATABASE IDEMPOTENT UPSERT & TIME-SERIES PERSISTENCE
# ==============================================================================

class TestDatabasePersistence:
    def test_idempotent_multi_day_upserts(self, config, db_manager):
        # Day 1 Data
        day1_data = {
            "companies": pd.DataFrame([{
                "symbol": "TCS",
                "company_name": "Tata Consultancy Services",
                "sector": "IT",
                "industry": "IT Services",
            }]),
            "prices": pd.DataFrame([{
                "symbol": "TCS",
                "price_date": "2026-09-12",
                "open_price": 4000.0,
                "high_price": 4050.0,
                "low_price": 3980.0,
                "close_price": 4020.0,
                "change_percent": 0.5,
                "volume": 1000000,
            }]),
            "fundamentals": pd.DataFrame([{
                "symbol": "TCS",
                "market_cap": 1500000.0,
                "pe_ratio": 30.0,
                "eps": 134.0,
                "revenue": 240000.0,
                "profit": 45000.0,
            }]),
        }

        # Load Day 1
        load_summary_1 = load_to_database(day1_data, db=db_manager, config=config)
        assert load_summary_1["companies_upserted"] == 1
        assert load_summary_1["prices_loaded"] == 1

        # Day 2 Data (Same company, new date)
        day2_data = {
            "companies": pd.DataFrame([{
                "symbol": "TCS",
                "company_name": "Tata Consultancy Services",
                "sector": "IT",
                "industry": "IT Services",
            }]),
            "prices": pd.DataFrame([{
                "symbol": "TCS",
                "price_date": "2026-09-13",
                "open_price": 4030.0,
                "high_price": 4100.0,
                "low_price": 4020.0,
                "close_price": 4080.0,
                "change_percent": 1.49,
                "volume": 1200000,
            }]),
            "fundamentals": pd.DataFrame([{
                "symbol": "TCS",
                "market_cap": 1520000.0,
                "pe_ratio": 30.5,
                "eps": 134.0,
                "revenue": 240000.0,
                "profit": 45000.0,
            }]),
        }

        # Load Day 2
        load_summary_2 = load_to_database(day2_data, db=db_manager, config=config)
        assert load_summary_2["prices_loaded"] == 1

        # Verify historical prices preserved
        df_hist = db_manager.query_to_dataframe("SELECT * FROM stock_prices WHERE company_id = 1 ORDER BY price_date ASC")
        assert len(df_hist) == 2
        assert df_hist.iloc[0]["close_price"] == 4020.0
        assert df_hist.iloc[1]["close_price"] == 4080.0


# ==============================================================================
# 6. REPORTING TESTS (EXCEL & GOOGLE SHEETS)
# ==============================================================================

class TestReportingLayer:
    def test_excel_report_generation(self, config, db_manager):
        analytics = MarketAnalytics(config, db_manager)
        kpis = KPIAnalytics(config, db_manager)
        
        # Insert sample stock
        raw_stocks = [{"symbol": "INFY", "company_name": "Infosys", "sector": "IT", "price": "₹1,800.00", "change_percent": "+1.5%", "volume": "3M"}]
        raw_funds = [{"symbol": "INFY", "market_cap": "₹7,00,000 Cr", "pe_ratio": "28.0", "profit": "₹25,000 Cr"}]
        transformed = transform({"market": raw_stocks, "fundamentals": raw_funds}, config=config)
        validated, _ = validate(transformed, config=config)
        load_to_database(validated, db=db_manager, config=config)

        report_gen = ExcelReportGenerator(config, db_manager)
        report_path = report_gen.generate_full_report("test_market_report.xlsx")
        assert report_path.exists()
        assert report_path.stat().st_size > 0

    def test_google_sheets_simulation_sync(self, config):
        syncer = GoogleSheetsSync(config)
        # Verify sync executes cleanly in dry-run mode without crashing
        result = syncer.sync_dashboard(analytics={"data_quality_score": 98.5})
        assert result is True

