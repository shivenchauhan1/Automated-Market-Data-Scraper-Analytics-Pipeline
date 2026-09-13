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
from pathlib import Path
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

from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager
from etl.extract import extract, save_raw_data
from etl.transform import transform
from etl.validate import validate, quarantine
from etl.quality import compute_data_quality
from etl.load import load_to_database
from analytics.market_analysis import run_analysis
from reports.excel_report import generate_excel_report
from reports.google_sheets import update_google_sheets


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

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter("[%(levelname)-7s] %(message)s")
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

    print("\n==================================================")
    print("       AUTOMATED MARKET DATA PIPELINE")
    print("==================================================")

    db = get_db_manager(config)
    run_id = db.start_pipeline_run(source="CLI_Main_Pipeline")
    start_time = time.time()

    try:
        # [1/7] Extract Data
        print("\n[1/7] Extracting market data...")
        raw_data = extract(pages=pages, config=config)
        save_raw_data(raw_data, config=config)
        extracted_count = len(raw_data.get("stocks", []))
        print(f"      ✓ {extracted_count} records extracted")

        # [2/7] Transform Data
        print("\n[2/7] Transforming data...")
        transformed_data = transform(raw_data, config=config)
        print("      ✓ Currency normalized")
        print("      ✓ Percentages normalized")

        # [3/7] Validate Schema & Data Quality
        print("\n[3/7] Validating schema & data quality...")
        valid_data, invalid_data = validate(transformed_data, config=config)
        quarantine_path = quarantine(invalid_data, config=config)
        
        dq_report = compute_data_quality(
            raw_data=raw_data,
            transformed_data=transformed_data,
            validated_data=valid_data,
            errors=invalid_data,
            config=config,
        )
        
        valid_count = len(valid_data["prices"])
        quarantined_count = sum(len(errs) for errs in invalid_data.values())
        print(f"      ✓ {valid_count} valid")
        if quarantined_count > 0:
            print(f"      ⚠ {quarantined_count} quarantined ({quarantine_path.name})")
        else:
            print("      ⚠ 0 quarantined")
        print(f"      ✓ Data Quality Score: {dq_report.quality_score:.2f}% (Grade: {dq_report.grade})")

        if dry_run:
            print("\n[DRY-RUN] Skipping database insert and report generation.")
            return True

        # [4/7] Load Relational Database
        print(f"\n[4/7] Loading {db.active_engine.upper()} database...")
        load_summary = load_to_database(valid_data, db=db, config=config)
        print(f"      ✓ Companies upserted: {load_summary.get('companies_upserted', 0)}")
        print(f"      ✓ Prices loaded: {load_summary.get('prices_loaded', 0)}")
        print(f"      ✓ Fundamentals loaded: {load_summary.get('fundamentals_loaded', 0)}")

        # [5/7] Run Analytics
        print("\n[5/7] Running analytics...")
        analytics = run_analysis(df=None, db=db, config=config)
        analytics["data_quality_score"] = dq_report.quality_score
        print("      ✓ Market breadth calculated")
        print("      ✓ Sector returns calculated")
        print("      ✓ Top gainers/losers calculated")
        print("      ✓ Historical technicals & volatility computed")

        # [6/7] Generating Reports
        print("\n[6/7] Generating reports...")
        if export_excel:
            report_path = generate_excel_report(valid_data, analytics=analytics, config=config)
            print(f"      ✓ Excel report generated ({report_path.name})")
        if sync_sheets:
            update_google_sheets(valid_data, analytics=analytics, config=config)
            print("      ✓ Google Sheets updated")

        elapsed = time.time() - start_time
        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=extracted_count,
            records_loaded=load_summary["total_records"],
            status="SUCCESS",
            data_quality_score=dq_report.quality_score,
        )

        # [7/7] Pipeline Complete Summary Banner
        print("\n[7/7] Pipeline complete\n")
        print(f"Records processed:  {extracted_count}")
        print(f"Records loaded:     {load_summary['total_records']}")
        print(f"Records rejected:   {quarantined_count}")
        print(f"Data Quality Score: {dq_report.quality_score:.2f}% ({dq_report.grade})")
        print(f"Execution time:     {elapsed:.2f}s")
        print("==================================================\n")

        return True

    except Exception as exc:
        logger.exception("❌ Pipeline execution failed: %s", exc)
        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=0,
            records_loaded=0,
            status="FAILED",
            error_message=str(exc),
        )
        return False


def main():
    """Parse arguments and start pipeline."""
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
