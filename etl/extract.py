"""
Extract Layer of ETL Pipeline.
Coordinates data ingestion from multi-page web scrapers, fundamental scrapers, and REST APIs.
Persists immutable raw data snapshots in date-partitioned folders: data/raw/YYYY-MM-DD/.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.config import Config, get_config
from scraper.stock_scraper import StockScraper, scrape_stocks
from scraper.fundamentals_scraper import FundamentalsScraper, scrape_fundamentals
from scraper.api_client import FinancialAPIClient

logger = logging.getLogger("MarketPipeline.Extract")


class MarketExtractor:
    """Orchestrates extraction across multiple heterogeneous market data sources."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.stock_scraper = StockScraper(self.config)
        self.fundamentals_scraper = FundamentalsScraper(self.config)
        self.api_client = FinancialAPIClient(config=self.config)

    def extract_all(
        self,
        total_pages: int = 4,
        include_api: bool = True,
        save_raw_snapshot: bool = True,
    ) -> Dict[str, Any]:
        """
        Execute full extraction process across all data sources.
        """
        start_time = datetime.now()
        logger.info("================== [PHASE 1: EXTRACTION] ==================")
        logger.info("Beginning multi-source extraction at %s...", start_time.strftime("%Y-%m-%d %H:%M:%S"))

        # 1. Scrape Multi-Page Stock Quotes
        raw_stocks = self.stock_scraper.scrape_multi_page(total_pages=total_pages)
        symbols = list({item["symbol"] for item in raw_stocks if "symbol" in item})

        # 2. Extract Company Fundamentals
        raw_fundamentals = self.fundamentals_scraper.fetch_fundamentals_for_symbols(symbols)

        # 3. Ingest REST API Quotes
        raw_api_quotes = []
        if include_api:
            raw_api_quotes = self.api_client.fetch_market_quotes_from_api(symbols[:5])

        extracted_payload = {
            "metadata": {
                "extracted_at": start_time.isoformat(),
                "stock_count": len(raw_stocks),
                "fundamentals_count": len(raw_fundamentals),
                "api_quotes_count": len(raw_api_quotes),
            },
            "market": raw_stocks,
            "stocks": raw_stocks,
            "fundamentals": raw_fundamentals,
            "api_quotes": raw_api_quotes,
        }

        # 4. Save Date-Partitioned Snapshots
        if save_raw_snapshot:
            self.save_raw_data(extracted_payload, start_time)

        elapsed = (datetime.now() - start_time).total_seconds()
        logger.info(
            "Extraction completed in %.2fs. Total extracted: %d stocks, %d fundamentals, %d API quotes.",
            elapsed,
            len(raw_stocks),
            len(raw_fundamentals),
            len(raw_api_quotes),
        )

        return extracted_payload

    def save_raw_data(self, payload: Dict[str, Any], timestamp: Optional[datetime] = None) -> Path:
        """
        Persist raw JSON snapshots in date-partitioned directory:
        data/raw/YYYY-MM-DD/stocks.json & fundamentals.json
        """
        timestamp = timestamp or datetime.now()
        date_str = timestamp.strftime("%Y-%m-%d")
        partition_dir = self.config.DATA_RAW_DIR / date_str
        partition_dir.mkdir(parents=True, exist_ok=True)

        # Save stocks.json
        stocks_path = partition_dir / "stocks.json"
        with open(stocks_path, "w", encoding="utf-8") as f:
            json.dump(payload.get("stocks", []), f, indent=2, ensure_ascii=False)

        # Save fundamentals.json
        fundamentals_path = partition_dir / "fundamentals.json"
        with open(fundamentals_path, "w", encoding="utf-8") as f:
            json.dump(payload.get("fundamentals", []), f, indent=2, ensure_ascii=False)

        # Save complete run snapshot
        time_str = timestamp.strftime("%H%M%S")
        full_snapshot_path = partition_dir / f"market_snapshot_{time_str}.json"
        with open(full_snapshot_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        logger.info("Persisted date-partitioned raw snapshots to: %s", partition_dir)
        return partition_dir


def extract(pages: int = 4, config: Optional[Config] = None) -> Dict[str, Any]:
    """Functional helper for extraction."""
    extractor = MarketExtractor(config)
    return extractor.extract_all(total_pages=pages)


def save_raw_data(raw_data: Dict[str, Any], config: Optional[Config] = None) -> Path:
    """Functional helper for raw data persistence."""
    extractor = MarketExtractor(config)
    return extractor.save_raw_data(raw_data)
