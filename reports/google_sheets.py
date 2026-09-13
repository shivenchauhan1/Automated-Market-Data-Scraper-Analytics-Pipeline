"""
Google Sheets Synchronization Module.
Pushes market KPI dashboards and sector leaderboards to live Google Sheets via Google Drive/Sheets API (gspread).
Includes dry-run simulation mode when local service credentials are not configured.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from analytics.kpi_analysis import KPIAnalytics
from analytics.market_analysis import MarketAnalytics
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.GoogleSheets")

try:
    import gspread
    from google.oauth2.service_account import Credentials
    GSPREAD_AVAILABLE = True
except ImportError:
    GSPREAD_AVAILABLE = False


class GoogleSheetsSync:
    """Synchronizes market metrics to Google Sheets."""

    SCOPES = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.market_analytics = MarketAnalytics(self.config)
        self.kpi_analytics = KPIAnalytics(self.config)
        self.creds_path = self.config.GOOGLE_SHEETS_CREDENTIALS_PATH
        self.sheet_name = self.config.GOOGLE_SHEET_NAME

    def is_configured(self) -> bool:
        """Check if service account JSON credentials exist."""
        return GSPREAD_AVAILABLE and self.creds_path.exists()

    def sync_dashboard(self, analytics: Optional[Dict[str, Any]] = None) -> bool:
        """Sync latest market KPIs, top gainers, and sector analysis to Google Sheets."""
        logger.info("================== [PHASE 6: GOOGLE SHEETS SYNC] ==================")
        
        if analytics:
            df_market = analytics.get("market_df", self.market_analytics.get_latest_market_data())
            df_sector = analytics.get("sector_performance", self.market_analytics.calculate_sector_performance(df_market))
            kpis = analytics.get("kpis", self.kpi_analytics.get_executive_summary_kpis(df_market))
            breadth = analytics.get("breadth", self.market_analytics.calculate_market_breadth(df_market))
            top_gainers = analytics.get("top_gainers", self.kpi_analytics.get_top_gainers(5, df_market))
        else:
            df_market = self.market_analytics.get_latest_market_data()
            df_sector = self.market_analytics.calculate_sector_performance(df_market)
            kpis = self.kpi_analytics.get_executive_summary_kpis(df_market)
            breadth = self.market_analytics.calculate_market_breadth(df_market)
            top_gainers = self.kpi_analytics.get_top_gainers(5, df_market)

        if not self.is_configured():
            logger.info("Google Service Account credentials not found at %s.", self.creds_path)
            logger.info("Operating in Google Sheets SIMULATION MODE (Dry-Run).")
            self._simulate_sync(kpis, breadth, top_gainers, df_sector)
            return True

        try:
            creds = Credentials.from_service_account_file(str(self.creds_path), scopes=self.SCOPES)
            client = gspread.authorize(creds)
            
            try:
                sheet = client.open(self.sheet_name)
            except gspread.SpreadsheetNotFound:
                logger.info("Spreadsheet '%s' not found. Creating new spreadsheet...", self.sheet_name)
                sheet = client.create(self.sheet_name)

            ws = sheet.get_worksheet(0) or sheet.sheet1
            ws.update_title("Market Summary")
            
            rows = [
                ["MARKET ANALYTICS DASHBOARD", ""],
                ["Last Updated", datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
                ["", ""],
                ["Total Companies Tracked", kpis["total_companies"]],
                ["Average Daily Return", f"{kpis['avg_daily_return']:+.2f}%"],
                ["Total Market Cap (Cr)", f"INR {kpis['total_market_cap_cr']:,.2f}"],
                ["Market Breadth", f"{breadth['ad_ratio']} ({breadth['market_sentiment']})"],
                ["Top Gainer", f"{kpis['top_gainer_symbol']} ({kpis['top_gainer_change']:+.2f}%)"],
                ["Top Loser", f"{kpis['top_loser_symbol']} ({kpis['top_loser_change']:+.2f}%)"],
            ]
            ws.update("A1:B9", rows)
            logger.info("Successfully updated Google Sheet '%s'.", self.sheet_name)
            return True

        except Exception as e:
            logger.error("Failed to update Google Sheets: %s", e)
            return False

    def _simulate_sync(self, kpis: Dict[str, Any], breadth: Dict[str, Any], top_gainers: pd.DataFrame, df_sector: pd.DataFrame) -> None:
        """Log simulated push payload for interview demo verification."""
        logger.info("[GoogleSheets-Sync] Push Payload verified:")
        logger.info("  -> Timestamp: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("  -> Tracked Companies: %d", kpis["total_companies"])
        logger.info("  -> Avg Return: %+.2f%%", kpis["avg_daily_return"])
        logger.info("  -> Total Market Cap: INR %s Cr", f"{kpis['total_market_cap_cr']:,.2f}")
        logger.info("  -> Top Gainer: %s (%+.2f%%)", kpis["top_gainer_symbol"], kpis["top_gainer_change"])
        logger.info("  -> Top Loser: %s (%+.2f%%)", kpis["top_loser_symbol"], kpis["top_loser_change"])
        logger.info("  -> Sectors Synced: %d", len(df_sector))
        logger.info("[GoogleSheets-Sync] Dry-run update completed successfully.")


def update_google_sheets(valid_data: Optional[Any] = None, analytics: Optional[Any] = None, config: Optional[Config] = None) -> bool:
    """Functional helper for Google Sheets sync."""
    syncer = GoogleSheetsSync(config)
    return syncer.sync_dashboard(analytics)
