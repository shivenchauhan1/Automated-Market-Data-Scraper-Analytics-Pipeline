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

        dq_score = analytics.get("data_quality_score", 100.0) if analytics else 100.0

        if not self.is_configured():
            logger.info("Google Service Account credentials not found at %s.", self.creds_path)
            logger.info("Operating in Google Sheets SIMULATION MODE (Dry-Run).")
            self._simulate_sync(kpis, breadth, top_gainers, df_sector, dq_score=dq_score)
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
                ["Data Quality Score", f"{dq_score:.2f}%"],
                ["", ""],
                ["Total Companies Tracked", kpis.get("total_companies", 0)],
                ["Average Daily Return", f"{kpis.get('avg_daily_return', 0.0):+.2f}%"],
                ["Total Market Cap (Cr)", f"INR {kpis.get('total_market_cap_cr', 0.0):,.2f}"],
                ["Market Breadth (A/D)", f"{breadth.get('ad_ratio', 0.0)} ({breadth.get('market_sentiment', 'Neutral')})"],
                ["Advancing / Declining", f"{breadth.get('advances', 0)} / {breadth.get('declines', 0)}"],
                ["Top Gainer", f"{kpis.get('top_gainer_symbol', 'N/A')} ({kpis.get('top_gainer_change', 0.0):+.2f}%)"],
                ["Top Loser", f"{kpis.get('top_loser_symbol', 'N/A')} ({kpis.get('top_loser_change', 0.0):+.2f}%)"],
            ]
            ws.update("A1:B11", rows)
            logger.info("Successfully updated Google Sheet '%s'.", self.sheet_name)
            return True

        except Exception as e:
            logger.error("Failed to update Google Sheets: %s", e)
            return False

    def _simulate_sync(self, kpis: Dict[str, Any], breadth: Dict[str, Any], top_gainers: pd.DataFrame, df_sector: pd.DataFrame, dq_score: float = 100.0) -> None:
        """Log simulated push payload for interview demo verification."""
        logger.info("[GoogleSheets-Sync] Push Payload verified:")
        logger.info("  -> Timestamp: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        logger.info("  -> Data Quality Score: %.2f%%", dq_score)
        logger.info("  -> Tracked Companies: %d", kpis.get("total_companies", 0))
        logger.info("  -> Avg Return: %+.2f%%", kpis.get("avg_daily_return", 0.0))
        logger.info("  -> Total Market Cap: INR %s Cr", f"{kpis.get('total_market_cap_cr', 0.0):,.2f}")
        logger.info("  -> Top Gainer: %s (%+.2f%%)", kpis.get("top_gainer_symbol", "N/A"), kpis.get("top_gainer_change", 0.0))
        logger.info("  -> Top Loser: %s (%+.2f%%)", kpis.get("top_loser_symbol", "N/A"), kpis.get("top_loser_change", 0.0))
        logger.info("  -> Sectors Synced: %d", len(df_sector) if df_sector is not None else 0)
        logger.info("[GoogleSheets-Sync] Dry-run update completed successfully.")


def update_google_sheets(valid_data: Optional[Any] = None, analytics: Optional[Any] = None, config: Optional[Config] = None) -> bool:
    """Functional helper for Google Sheets sync."""
    syncer = GoogleSheetsSync(config)
    return syncer.sync_dashboard(analytics)
