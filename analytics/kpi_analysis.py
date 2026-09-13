"""
KPI Analysis Module.
Generates executive financial indicators, top gainers/losers, valuation outliers, and company profile metrics.
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
        - Advancing Stocks Count
        - Declining Stocks Count
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
                "advancing_count": 0,
                "declining_count": 0,
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

        avg_return = df["change_percent"].mean() if "change_percent" in df.columns else 0.0
        total_mcap = df["market_cap"].sum() if "market_cap" in df.columns else 0.0
        avg_pe = df["pe_ratio"].dropna().mean() if "pe_ratio" in df.columns else 0.0
        advancing = int((df["change_percent"] > 0).sum()) if "change_percent" in df.columns else 0
        declining = int((df["change_percent"] < 0).sum()) if "change_percent" in df.columns else 0

        sorted_by_change = df.sort_values("change_percent", ascending=False) if "change_percent" in df.columns else df
        top_gainer = sorted_by_change.iloc[0] if not sorted_by_change.empty else None
        top_loser = sorted_by_change.iloc[-1] if not sorted_by_change.empty else None

        sorted_by_vol = df.sort_values("volume", ascending=False) if "volume" in df.columns else df
        most_active = sorted_by_vol.iloc[0] if not sorted_by_vol.empty else None

        return {
            "total_companies": len(df),
            "advancing_count": advancing,
            "declining_count": declining,
            "avg_daily_return": round(float(avg_return), 2) if not pd.isna(avg_return) else 0.0,
            "total_market_cap_cr": round(float(total_mcap), 2) if not pd.isna(total_mcap) else 0.0,
            "avg_pe_ratio": round(float(avg_pe), 2) if not pd.isna(avg_pe) else 0.0,
            "top_gainer_symbol": top_gainer["symbol"] if top_gainer is not None else "N/A",
            "top_gainer_change": round(float(top_gainer["change_percent"]), 2) if top_gainer is not None and "change_percent" in top_gainer else 0.0,
            "top_loser_symbol": top_loser["symbol"] if top_loser is not None else "N/A",
            "top_loser_change": round(float(top_loser["change_percent"]), 2) if top_loser is not None and "change_percent" in top_loser else 0.0,
            "most_active_symbol": most_active["symbol"] if most_active is not None else "N/A",
            "most_active_volume": int(most_active["volume"]) if most_active is not None and "volume" in most_active and not pd.isna(most_active["volume"]) else 0,
        }

    def get_top_gainers(self, n: int = 10, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Get top N gainers ordered by percentage return."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "change_percent" not in df.columns:
            return pd.DataFrame()
        return df.sort_values("change_percent", ascending=False).head(n).reset_index(drop=True)

    def get_top_losers(self, n: int = 10, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Get top N losers ordered by percentage change ascending."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "change_percent" not in df.columns:
            return pd.DataFrame()
        return df.sort_values("change_percent", ascending=True).head(n).reset_index(drop=True)

    def get_undervalued_picks(self, max_pe: float = 25.0, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Identify profitable companies with P/E below threshold."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "pe_ratio" not in df.columns or "profit" not in df.columns:
            return pd.DataFrame()
        filtered = df[(df["pe_ratio"] > 0) & (df["pe_ratio"] <= max_pe) & (df["profit"] > 0)]
        return filtered.sort_values("pe_ratio", ascending=True).reset_index(drop=True)

    def get_stock_profile(self, symbol: str) -> Dict[str, Any]:
        """Fetch comprehensive stock profile combining fundamentals and historical price analytics."""
        sym = symbol.upper()
        df_latest = self.market_analytics.get_latest_market_data()
        stock_row = df_latest[df_latest["symbol"] == sym]

        historical_metrics = self.market_analytics.calculate_stock_historical_metrics(sym)

        if not stock_row.empty:
            r = stock_row.iloc[0]
            profile = {
                "symbol": sym,
                "company_name": r.get("company_name", sym),
                "sector": r.get("sector", "General"),
                "industry": r.get("industry", "General"),
                "current_price": r.get("close_price", historical_metrics.get("current_price")),
                "daily_change_pct": r.get("change_percent", historical_metrics.get("daily_change_pct")),
                "volume": int(r.get("volume", 0)) if not pd.isna(r.get("volume")) else 0,
                "market_cap": r.get("market_cap"),
                "pe_ratio": r.get("pe_ratio"),
                "eps": r.get("eps"),
                "revenue": r.get("revenue"),
                "profit": r.get("profit"),
                "debt": r.get("debt"),
            }
        else:
            profile = {
                "symbol": sym,
                "company_name": sym,
                "sector": "General",
                "industry": "General",
                "current_price": historical_metrics.get("current_price"),
                "daily_change_pct": historical_metrics.get("daily_change_pct"),
                "volume": 0,
                "market_cap": None,
                "pe_ratio": None,
                "eps": None,
                "revenue": None,
                "profit": None,
                "debt": None,
            }

        profile.update(historical_metrics)
        return profile
