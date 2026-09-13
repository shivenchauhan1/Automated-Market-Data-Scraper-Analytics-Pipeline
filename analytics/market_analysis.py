"""
Market Analytics Module.
Performs sector-level aggregation, market breadth calculations, and statistical distribution analysis.
"""

import logging
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager

logger = logging.getLogger("MarketPipeline.MarketAnalytics")


class MarketAnalytics:
    """Computes macroeconomic and sector-wide market performance metrics."""

    def __init__(self, config: Optional[Config] = None, db_manager: Optional[DatabaseManager] = None):
        self.config = config or get_config()
        self.db = db_manager or get_db_manager(self.config)

    def get_latest_market_data(self) -> pd.DataFrame:
        """Fetch latest stock prices merged with company metadata and fundamentals."""
        query = """
        SELECT 
            c.symbol,
            c.company_name,
            c.sector,
            c.industry,
            p.price_date,
            p.open_price,
            p.high_price,
            p.low_price,
            p.close_price,
            p.change_percent,
            p.volume,
            f.market_cap,
            f.pe_ratio,
            f.eps,
            f.revenue,
            f.profit,
            f.debt
        FROM companies c
        JOIN stock_prices p ON c.company_id = p.company_id
        LEFT JOIN fundamentals f ON c.company_id = f.company_id
        WHERE p.price_date = (SELECT MAX(price_date) FROM stock_prices)
        """
        return self.db.query_to_dataframe(query)

    def calculate_sector_performance(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Calculate aggregated performance metrics grouped by sector.
        Returns DataFrame with Average Return (%), Total Market Cap, Total Volume, and Stock Count.
        """
        if df is None:
            df = self.get_latest_market_data()

        if df.empty:
            return pd.DataFrame(columns=["sector", "company_count", "avg_return_pct", "total_market_cap_cr", "total_volume", "advancers", "decliners"])

        sector_stats = []
        for sector, group in df.groupby("sector"):
            avg_return = group["change_percent"].mean()
            total_mcap = group["market_cap"].sum()
            total_vol = group["volume"].sum()
            advancers = (group["change_percent"] > 0).sum()
            decliners = (group["change_percent"] < 0).sum()
            avg_pe = group["pe_ratio"].mean()

            sector_stats.append({
                "sector": sector,
                "company_count": len(group),
                "avg_return_pct": round(float(avg_return), 2) if not pd.isna(avg_return) else 0.0,
                "total_market_cap_cr": round(float(total_mcap), 2) if not pd.isna(total_mcap) else 0.0,
                "total_volume": int(total_vol) if not pd.isna(total_vol) else 0,
                "avg_pe_ratio": round(float(avg_pe), 2) if not pd.isna(avg_pe) else None,
                "advancers": int(advancers),
                "decliners": int(decliners),
            })

        sector_df = pd.DataFrame(sector_stats).sort_values("avg_return_pct", ascending=False).reset_index(drop=True)
        return sector_df

    def calculate_market_breadth(self, df: Optional[pd.DataFrame] = None) -> Dict[str, Any]:
        """
        Compute overall market breadth: Advancers, Decliners, Unchanged, A/D Ratio.
        """
        if df is None:
            df = self.get_latest_market_data()

        if df.empty:
            return {"advancers": 0, "decliners": 0, "unchanged": 0, "ad_ratio": 1.0, "total_tracked": 0}

        advancers = int((df["change_percent"] > 0).sum())
        decliners = int((df["change_percent"] < 0).sum())
        unchanged = int((df["change_percent"] == 0).sum())
        total = len(df)
        ad_ratio = round(advancers / decliners, 2) if decliners > 0 else (float(advancers) if advancers > 0 else 1.0)

        return {
            "advancers": advancers,
            "decliners": decliners,
            "unchanged": unchanged,
            "ad_ratio": ad_ratio,
            "total_tracked": total,
            "market_sentiment": "Bullish" if advancers > decliners else ("Bearish" if decliners > advancers else "Neutral"),
        }


def run_analysis(df: Optional[pd.DataFrame] = None, db: Optional[DatabaseManager] = None, config: Optional[Config] = None) -> Dict[str, Any]:
    """Execute complete analytics computation suite."""
    from analytics.kpi_analysis import KPIAnalytics
    m_analytics = MarketAnalytics(config, db)
    k_analytics = KPIAnalytics(config, db)

    if df is None:
        df = m_analytics.get_latest_market_data()

    breadth = m_analytics.calculate_market_breadth(df)
    sector_df = m_analytics.calculate_sector_performance(df)
    top_gainers = k_analytics.get_top_gainers(10, df)
    top_losers = k_analytics.get_top_losers(10, df)
    kpis = k_analytics.get_executive_summary_kpis(df)

    return {
        "breadth": breadth,
        "sector_performance": sector_df,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "kpis": kpis,
        "market_df": df,
    }
