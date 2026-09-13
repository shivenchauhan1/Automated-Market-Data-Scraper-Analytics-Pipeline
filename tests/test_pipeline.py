"""
Comprehensive Unit & Integration Test Suite.
Verifies transformation cleaning functions, Pydantic schema validation, scraper HTML parsing, database upserts, and analytics computations.
"""

import os
from pathlib import Path
import pytest
import pandas as pd

from config.config import Config, get_config
from database.db_connection import DatabaseManager
from etl.transform import MarketTransformer
from etl.validate import CompanyModel, FundamentalModel, MarketValidator, StockPriceModel
from etl.load import MarketLoader
from scraper.stock_scraper import StockScraper
from scraper.fundamentals_scraper import FundamentalsScraper
from scraper.api_client import FinancialApiClient
from analytics.market_analysis import MarketAnalytics
from analytics.kpi_analysis import KPIAnalytics
from reports.excel_report import ExcelReportGenerator


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
        assert MarketTransformer.clean_price("₹1,450.50") == 1450.50
        assert MarketTransformer.clean_price("$2,980.00") == 2980.00
        assert MarketTransformer.clean_price("1450.50") == 1450.50
        assert MarketTransformer.clean_price("1,234.56") == 1234.56
        assert MarketTransformer.clean_price("N/A") is None
        assert MarketTransformer.clean_price("-") is None
        assert MarketTransformer.clean_price(None) is None

    def test_clean_percentage(self):
        assert MarketTransformer.clean_percentage("+1.25%") == 1.25
        assert MarketTransformer.clean_percentage("-0.45%") == -0.45
        assert MarketTransformer.clean_percentage("0.82%") == 0.82
        assert MarketTransformer.clean_percentage("1.25") == 1.25
        assert MarketTransformer.clean_percentage("N/A") is None
        assert MarketTransformer.clean_percentage(None) is None

    def test_clean_volume(self):
        assert MarketTransformer.clean_volume("4.2M") == 4_200_000
        assert MarketTransformer.clean_volume("500K") == 500_000
        assert MarketTransformer.clean_volume("1.5B") == 1_500_000_000
        assert MarketTransformer.clean_volume("2,340") == 2340
        assert MarketTransformer.clean_volume("N/A") is None

    def test_clean_market_cap_or_financial(self):
        assert MarketTransformer.clean_market_cap_or_financial("₹5,23,450 Cr") == 523450.0
        assert MarketTransformer.clean_market_cap_or_financial("-₹4,900 Cr") == -4900.0
        assert MarketTransformer.clean_market_cap_or_financial("10,000") == 10000.0


# ==============================================================================
# 2. SCHEMA VALIDATION TESTS
# ==============================================================================

class TestMarketValidator:
    def test_company_model_valid(self):
        comp = CompanyModel(symbol="reliance", company_name="Reliance Industries", sector="Energy")
        assert comp.symbol == "RELIANCE"
        assert comp.sector == "Energy"

    def test_company_model_invalid_empty_symbol(self):
        with pytest.raises(Exception):
            CompanyModel(symbol="   ", company_name="Invalid Corp")

    def test_stock_price_model_valid(self):
        price = StockPriceModel(symbol="TCS", price_date="2026-09-13", close_price=4120.0, volume=2100000)
        assert price.close_price == 4120.0
        assert price.price_date == "2026-09-13"

    def test_stock_price_model_invalid_negative_price(self):
        with pytest.raises(Exception):
            StockPriceModel(symbol="TCS", price_date="2026-09-13", close_price=-50.0)

    def test_validate_dataframe_quarantine(self):
        df_raw = pd.DataFrame([
            {"symbol": "TCS", "price_date": "2026-09-13", "close_price": 4000.0, "volume": 1000},
            {"symbol": "BAD", "price_date": "invalid-date", "close_price": 100.0, "volume": 100},
            {"symbol": "NEG", "price_date": "2026-09-13", "close_price": -10.0, "volume": 50},
        ])
        valid_df, errors = MarketValidator.validate_dataframe(df_raw, StockPriceModel)
        assert len(valid_df) == 1
        assert len(errors) == 2
        assert valid_df.iloc[0]["symbol"] == "TCS"


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
        assert "₹" in records[0]["price"]

    def test_fundamentals_scraper(self, config):
        f_scraper = FundamentalsScraper(config)
        results = f_scraper.fetch_fundamentals_for_symbols(["RELIANCE", "TCS"])
        assert len(results) == 2
        assert results[0]["symbol"] == "RELIANCE"
        assert "pe_ratio" in results[0]

    def test_api_client_quotes(self, config):
        client = FinancialApiClient(config)
        quotes = client.fetch_market_quotes_from_api(["RELIANCE", "INFY"])
        assert len(quotes) == 2
        assert quotes[0]["symbol"] in ["RELIANCE", "INFY"]


# ==============================================================================
# 4. DATABASE & ETL INTEGRATION TESTS
# ==============================================================================

class TestDatabaseAndETL:
    def test_end_to_end_load_and_analytics(self, config, db_manager):
        # 1. Transform seed data
        transformer = MarketTransformer(config)
        raw_stocks = [
            {"symbol": "RELIANCE", "company_name": "Reliance", "sector": "Energy", "price": "₹3,000.00", "change_percent": "+2.00%", "volume": "5M"},
            {"symbol": "TCS", "company_name": "Tata Consultancy", "sector": "IT", "price": "₹4,000.00", "change_percent": "-1.00%", "volume": "2M"},
        ]
        raw_funds = [
            {"symbol": "RELIANCE", "market_cap": "₹20,00,000 Cr", "pe_ratio": "25.0", "profit": "₹80,000 Cr"},
            {"symbol": "TCS", "market_cap": "₹15,00,000 Cr", "pe_ratio": "30.0", "profit": "₹45,000 Cr"},
        ]
        transformed = transformer.transform_all({"stocks": raw_stocks, "fundamentals": raw_funds})

        # 2. Validate
        validator = MarketValidator(config)
        validated, errs = validator.validate_all(transformed)
        assert len(validated["companies"]) == 2
        assert len(validated["prices"]) == 2

        # 3. Load into DB
        loader = MarketLoader(config, db_manager)
        load_stats = loader.load_all(validated)
        assert load_stats["companies"] == 2
        assert load_stats["prices"] == 2

        # 4. Analytics
        m_analytics = MarketAnalytics(config, db_manager)
        df_market = m_analytics.get_latest_market_data()
        assert len(df_market) == 2

        breadth = m_analytics.calculate_market_breadth(df_market)
        assert breadth["advancers"] == 1
        assert breadth["decliners"] == 1

        sector_df = m_analytics.calculate_sector_performance(df_market)
        assert len(sector_df) == 2

        kpi_analytics = KPIAnalytics(config, db_manager)
        kpis = kpi_analytics.get_executive_summary_kpis(df_market)
        assert kpis["total_companies"] == 2
        assert kpis["top_gainer_symbol"] == "RELIANCE"
        assert kpis["top_loser_symbol"] == "TCS"


# ==============================================================================
# 5. EXCEL REPORT GENERATION TEST
# ==============================================================================

class TestExcelReportGenerator:
    def test_generate_report(self, config, db_manager):
        # Populate test data first
        transformer = MarketTransformer(config)
        raw_stocks = [{"symbol": "INFY", "company_name": "Infosys", "sector": "IT", "price": "₹1,800.00", "change_percent": "+1.5%", "volume": "3M"}]
        raw_funds = [{"symbol": "INFY", "market_cap": "₹7,00,000 Cr", "pe_ratio": "28.0", "profit": "₹25,000 Cr"}]
        transformed = transformer.transform_all({"stocks": raw_stocks, "fundamentals": raw_funds})
        validator = MarketValidator(config)
        validated, _ = validator.validate_all(transformed)
        loader = MarketLoader(config, db_manager)
        loader.load_all(validated)

        # Generate report
        report_gen = ExcelReportGenerator(config)
        report_gen.market_analytics.db = db_manager
        report_gen.kpi_analytics.db = db_manager
        report_gen.kpi_analytics.market_analytics.db = db_manager
        
        output_path = report_gen.generate_full_report("test_report.xlsx")
        assert output_path.exists()
        assert output_path.stat().st_size > 0
