"""
Master Pipeline Orchestrator.
Executes end-to-end ETL: Web Scraping -> API Ingestion -> Cleansing -> Pydantic Validation -> Database Loading -> Analytics -> Excel & Google Sheets Reporting.

Usage:
    python main.py
    python main.py --pages 4 --export-excel --sync-sheets
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from typing import Optional

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from tabulate import tabulate

from analytics.kpi_analysis import KPIAnalytics
from analytics.market_analysis import MarketAnalytics
from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager
from etl.extract import MarketExtractor
from etl.load import MarketLoader
from etl.transform import MarketTransformer
from etl.validate import MarketValidator
from reports.excel_report import ExcelReportGenerator
from reports.google_sheets import GoogleSheetsSync


def setup_logging(config: Config) -> logging.Logger:
    """Configure structured console and file logging."""
    logger = logging.getLogger("MarketPipeline")
    logger.setLevel(getattr(logging, config.LOG_LEVEL, logging.INFO))
    logger.handlers.clear()

    # File Handler (UTF-8)
    file_handler = logging.FileHandler(config.LOG_FILE_PATH, encoding="utf-8")
    file_formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)-8s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console Handler (StreamHandler with errors='replace')
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter(
        "[%(levelname)-7s] %(message)s"
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def run_pipeline(
    pages: int = 4,
    export_excel: bool = True,
    sync_sheets: bool = True,
    include_api: bool = True,
    dry_run: bool = False,
) -> bool:
    """Execute complete data engineering and reporting lifecycle."""
    config = get_config()
    logger = setup_logging(config)

    start_time = time.time()
    logger.info("================================================================")
    logger.info("🚀 AUTOMATED MARKET DATA SCRAPER & ANALYTICS PIPELINE")
    logger.info("================================================================")
    logger.info("Execution initiated at: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    db = get_db_manager(config)
    run_id = db.start_pipeline_run(source="CLI_Main_Pipeline")

    try:
        # 1. EXTRACT
        logger.info("[1/6] Extracting market data across %d pages & REST API...", pages)
        extractor = MarketExtractor(config)
        raw_payload = extractor.extract_all(total_pages=pages, include_api=include_api)
        records_extracted = len(raw_payload.get("stocks", []))
        logger.info("[INFO] %d raw stock records extracted.", records_extracted)

        # 2. TRANSFORM
        logger.info("[2/6] Cleaning, normalizing, and casting data types...")
        transformer = MarketTransformer(config)
        transformed_data = transformer.transform_all(raw_payload)

        # 3. VALIDATE
        logger.info("[3/6] Enforcing Pydantic v2 schema constraints...")
        validator = MarketValidator(config)
        validated_data, quarantine_errors = validator.validate_all(transformed_data)
        logger.info("[INFO] Validation successful: 0 fatal schema violations.")

        if dry_run:
            logger.info("[DRY-RUN] Skipping database insert and external syncs.")
            return True

        # 4. LOAD
        logger.info("[4/6] Loading into %s relational database...", db.active_engine.upper())
        loader = MarketLoader(config, db)
        load_stats = loader.load_all(validated_data)
        logger.info("[INFO] %d records loaded into database successfully.", load_stats["total_records"])

        # 5. ANALYZE & EXCEL REPORTING
        if export_excel:
            logger.info("[5/6] Generating multi-sheet Excel KPI report...")
            excel_gen = ExcelReportGenerator(config)
            report_path = excel_gen.generate_full_report()
            logger.info("[INFO] Excel report generated: %s", report_path.name)

        # 6. GOOGLE SHEETS SYNC
        if sync_sheets:
            logger.info("[6/6] Synchronizing KPI dashboard to Google Sheets...")
            sheets_sync = GoogleSheetsSync(config)
            sheets_sync.sync_dashboard()
            logger.info("[INFO] Google Sheets sync completed.")

        # Analytics Executive Banner
        kpi_analytics = KPIAnalytics(config, db)
        market_analytics = MarketAnalytics(config, db)
        kpis = kpi_analytics.get_executive_summary_kpis()
        breadth = market_analytics.calculate_market_breadth()

        elapsed = time.time() - start_time
        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=records_extracted,
            records_loaded=load_stats["total_records"],
            status="SUCCESS",
        )

        logger.info("================================================================")
        logger.info("[SUMMARY] EXECUTIVE MARKET SUMMARY")
        logger.info("================================================================")
        summary_table = [
            ["Tracked Companies", str(kpis["total_companies"])],
            ["Average Daily Return", f"{kpis['avg_daily_return']:+.2f}%"],
            ["Total Market Cap", f"INR {kpis['total_market_cap_cr']:,.2f} Cr"],
            ["Market Breadth", f"{breadth['ad_ratio']} ({breadth['market_sentiment']})"],
            ["Top Gainer", f"{kpis['top_gainer_symbol']} ({kpis['top_gainer_change']:+.2f}%)"],
            ["Top Loser", f"{kpis['top_loser_symbol']} ({kpis['top_loser_change']:+.2f}%)"],
            ["Execution Duration", f"{elapsed:.2f} seconds"],
            ["Database Engine", db.active_engine.upper()],
        ]
        print("\n" + tabulate(summary_table, headers=["KPI Metric", "Value"], tablefmt="grid") + "\n")

        logger.info("Pipeline completed successfully in %.2f seconds.", elapsed)
        return True

    except Exception as exc:
        logger.exception("❌ Pipeline encountered an unhandled exception: %s", exc)
        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=0,
            records_loaded=0,
            status="FAILED",
            error_message=str(exc),
        )
        return False


def main():
    """Parse arguments and start execution."""
    parser = argparse.ArgumentParser(
        description="Automated Market Data Scraper & Analytics Pipeline"
    )
    parser.add_argument("--pages", type=int, default=4, help="Number of pages to scrape (default: 4)")
    parser.add_argument("--no-excel", action="store_true", help="Skip Excel report generation")
    parser.add_argument("--no-sheets", action="store_true", help="Skip Google Sheets sync")
    parser.add_argument("--no-api", action="store_true", help="Skip REST API integration")
    parser.add_argument("--dry-run", action="store_true", help="Perform extraction and transformation only")

    args = parser.parse_args()

    success = run_pipeline(
        pages=args.pages,
        export_excel=not args.no_excel,
        sync_sheets=not args.no_sheets,
        include_api=not args.no_api,
        dry_run=args.dry_run,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
