"""
Comprehensive Unit & Integration Test Suite.
Verifies transformation cleaning functions, Pydantic schema validation, quarantine handling, scraper HTML parsing, database upserts, and analytics computations.
"""

import json
import os
from pathlib import Path
import pytest
import pandas as pd

from config.config import Config, get_config
from database.db_connection import DatabaseManager
from etl.transform import clean_price, clean_percentage, clean_volume, clean_market_cap_or_financial, transform_stock, transform
from etl.validate import StockRecord, FundamentalRecord, CompanyRecord, MarketValidator, validate, quarantine
from etl.load import load_to_database, MarketLoader
from scraper.stock_scraper import StockScraper, scrape_stocks
from scraper.fundamentals_scraper import FundamentalsScraper, scrape_fundamentals
from scraper.api_client import FinancialAPIClient
from analytics.market_analysis import MarketAnalytics, run_analysis
from analytics.kpi_analysis import KPIAnalytics
from reports.excel_report import ExcelReportGenerator, generate_excel_report


@pytest.fixture
def config(tmp_path):
    """Create isolated test config using temporary SQLite database."""
    test_cfg = Config()
    test_cfg.DB_TYPE = "sqlite"
    test_cfg.SQLITE_DB_PATH = tmp_path / "test_market.db"
    test_cfg.DATA_RAW_DIR = tmp_path / "raw"
    test_cfg.DATA_PROCESSED_DIR = tmp_path / "processed"
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
            "volume": "4.2M"
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

    def test_quarantine_flow(self, config):
        df_raw = pd.DataFrame([
            {"symbol": "TCS", "price_date": "2026-09-13", "close_price": 4000.0, "volume": 1000},
            {"symbol": "NEG", "price_date": "2026-09-13", "close_price": -10.0, "volume": 50},
        ])
        validator = MarketValidator(config)
        valid_df, errors = validator.validate_dataframe(df_raw, StockRecord)
        assert len(valid_df) == 1
        assert len(errors) == 1

        quarantine_path = validator.quarantine_invalid_records({"prices": errors})
        assert quarantine_path is not None
        assert quarantine_path.exists()
        with open(quarantine_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data["total_quarantined_records"] == 1


# ==============================================================================
# 3. SCRAPER & PARSING TESTS
# ==============================================================================

class TestScrapers:
    def test_stock_scraper_parse_html(self, config):
        scraper = StockScraper(config)
        html = scraper.generate_simulated_html(page_num=1, total_pages=2)
        records = scraper.parse_stock_html(html, page_num=1)
        assert len(records) == 5
        assert records[0]["symbol"] == "RELIANCE"

    def test_scrape_stocks_helper(self, config):
        records = scrape_stocks(pages=2, config=config)
        assert len(records) == 10

    def test_fundamentals_scraper(self, config):
        f_scraper = FundamentalsScraper(config)
        results = f_scraper.fetch_fundamentals_for_symbols(["RELIANCE", "TCS"])
        assert len(results) == 2
        assert results[0]["symbol"] == "RELIANCE"
        assert "pe_ratio" in results[0]

    def test_api_client_quotes(self, config):
        client = FinancialAPIClient(config=config)
        quote = client.get_market_data("RELIANCE")
        assert quote["symbol"] == "RELIANCE"
        assert quote["price"] > 0


# ==============================================================================
# 4. DATABASE & ETL INTEGRATION TESTS
# ==============================================================================

class TestDatabaseAndETL:
    def test_end_to_end_load_and_analytics(self, config, db_manager):
        # 1. Transform seed data
        raw_stocks = [
            {"symbol": "RELIANCE", "company_name": "Reliance", "sector": "Energy", "price": "₹3,000.00", "change_percent": "+2.00%", "volume": "5M"},
            {"symbol": "TCS", "company_name": "Tata Consultancy", "sector": "IT", "price": "₹4,000.00", "change_percent": "-1.00%", "volume": "2M"},
        ]
        raw_funds = [
            {"symbol": "RELIANCE", "market_cap": "₹20,00,000 Cr", "pe_ratio": "25.0", "profit": "₹80,000 Cr"},
            {"symbol": "TCS", "market_cap": "₹15,00,000 Cr", "pe_ratio": "30.0", "profit": "₹45,000 Cr"},
        ]
        transformed = transform({"market": raw_stocks, "fundamentals": raw_funds}, config=config)

        # 2. Validate
        validated, errs = validate(transformed, config=config)
        assert len(validated["companies"]) == 2
        assert len(validated["prices"]) == 2

        # 3. Load into DB
        load_stats = load_to_database(validated, db=db_manager, config=config)
        assert load_stats["companies"] == 2
        assert load_stats["prices"] == 2

        # 4. Analytics
        analysis = run_analysis(db=db_manager, config=config)
        breadth = analysis["breadth"]
        assert breadth["advancers"] == 1
        assert breadth["decliners"] == 1
        assert len(analysis["sector_performance"]) == 2


# ==============================================================================
# 5. EXCEL REPORT GENERATION TEST
# ==============================================================================

class TestExcelReportGenerator:
    def test_generate_report(self, config, db_manager):
        raw_stocks = [{"symbol": "INFY", "company_name": "Infosys", "sector": "IT", "price": "₹1,800.00", "change_percent": "+1.5%", "volume": "3M"}]
        raw_funds = [{"symbol": "INFY", "market_cap": "₹7,00,000 Cr", "pe_ratio": "28.0", "profit": "₹25,000 Cr"}]
        transformed = transform({"market": raw_stocks, "fundamentals": raw_funds}, config=config)
        validated, _ = validate(transformed, config=config)
        load_to_database(validated, db=db_manager, config=config)

        report_gen = ExcelReportGenerator(config)
        report_gen.market_analytics.db = db_manager
        report_gen.kpi_analytics.db = db_manager
        report_gen.kpi_analytics.market_analytics.db = db_manager
        
        output_path = report_gen.generate_full_report("test_report.xlsx")
        assert output_path.exists()
        assert output_path.stat().st_size > 0
