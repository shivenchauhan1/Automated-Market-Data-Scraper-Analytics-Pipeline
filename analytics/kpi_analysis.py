"""
KPI Analysis Module.
Generates executive financial indicators, top gainers/losers, valuation outliers, and market summary metrics.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from analytics.market_analysis import MarketAnalytics
from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager

logger = logging.getLogger("MarketPipeline.KPIAnalytics")


class KPIAnalytics:
    """Calculates executive financial KPIs and leaderboards for reports and dashboards."""

    def __init__(self, config: Optional[Config] = None, db_manager: Optional[DatabaseManager] = None):
        self.config = config or get_config()
        self.db = db_manager or get_db_manager(self.config)
        self.market_analytics = MarketAnalytics(self.config, self.db)

    def get_executive_summary_kpis(self, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Generate high-level market KPI cards:
        - Total Companies Tracked
        - Average Daily Return
        - Total Market Capitalization
        - Top Gainer & Top Loser
        - Average Market P/E
        """
        if df is None:
            df = self.market_analytics.get_latest_market_data()

        if df.empty:
            return {
                "total_companies": 0,
                "avg_daily_return": 0.0,
                "total_market_cap_cr": 0.0,
                "avg_pe_ratio": 0.0,
                "top_gainer_symbol": "N/A",
                "top_gainer_change": 0.0,
                "top_loser_symbol": "N/A",
                "top_loser_change": 0.0,
                "most_active_symbol": "N/A",
                "most_active_volume": 0,
            }

        avg_return = df["change_percent"].mean()
        total_mcap = df["market_cap"].sum()
        avg_pe = df["pe_ratio"].dropna().mean()

        sorted_by_change = df.sort_values("change_percent", ascending=False)
        top_gainer = sorted_by_change.iloc[0] if not sorted_by_change.empty else None
        top_loser = sorted_by_change.iloc[-1] if not sorted_by_change.empty else None

        sorted_by_vol = df.sort_values("volume", ascending=False)
        most_active = sorted_by_vol.iloc[0] if not sorted_by_vol.empty else None

        return {
            "total_companies": len(df),
            "avg_daily_return": round(float(avg_return), 2) if not pd.isna(avg_return) else 0.0,
            "total_market_cap_cr": round(float(total_mcap), 2) if not pd.isna(total_mcap) else 0.0,
            "avg_pe_ratio": round(float(avg_pe), 2) if not pd.isna(avg_pe) else 0.0,
            "top_gainer_symbol": top_gainer["symbol"] if top_gainer is not None else "N/A",
            "top_gainer_change": round(float(top_gainer["change_percent"]), 2) if top_gainer is not None else 0.0,
            "top_loser_symbol": top_loser["symbol"] if top_loser is not None else "N/A",
            "top_loser_change": round(float(top_loser["change_percent"]), 2) if top_loser is not None else 0.0,
            "most_active_symbol": most_active["symbol"] if most_active is not None else "N/A",
            "most_active_volume": int(most_active["volume"]) if most_active is not None else 0,
        }

    def get_top_gainers(self, n: int = 5, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Get top N gainers ordered by percentage return."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty:
            return pd.DataFrame()
        return df.sort_values("change_percent", ascending=False).head(n).reset_index(drop=True)

    def get_top_losers(self, n: int = 5, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Get top N losers ordered by percentage change ascending."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty:
            return pd.DataFrame()
        return df.sort_values("change_percent", ascending=True).head(n).reset_index(drop=True)

    def get_undervalued_picks(self, max_pe: float = 25.0, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Identify profitable companies with P/E below threshold."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty:
            return pd.DataFrame()
        filtered = df[(df["pe_ratio"] > 0) & (df["pe_ratio"] <= max_pe) & (df["profit"] > 0)]
        return filtered.sort_values("pe_ratio", ascending=True).reset_index(drop=True)
