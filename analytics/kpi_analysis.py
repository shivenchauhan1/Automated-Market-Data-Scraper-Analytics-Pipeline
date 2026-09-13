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
        """Get top N gainers ordered by percentage return (one record per company)."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "change_percent" not in df.columns:
            return pd.DataFrame()
        df_clean = df.drop_duplicates(subset=["symbol"]) if "symbol" in df.columns else df
        return df_clean.sort_values("change_percent", ascending=False).head(n).reset_index(drop=True)

    def get_top_losers(self, n: int = 10, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Get top N losers ordered by percentage change ascending (one record per company)."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "change_percent" not in df.columns:
            return pd.DataFrame()
        df_clean = df.drop_duplicates(subset=["symbol"]) if "symbol" in df.columns else df
        return df_clean.sort_values("change_percent", ascending=True).head(n).reset_index(drop=True)

    def get_undervalued_picks(self, max_pe: float = 25.0, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """Identify profitable companies with P/E below threshold."""
        if df is None:
            df = self.market_analytics.get_latest_market_data()
        if df.empty or "pe_ratio" not in df.columns or "profit" not in df.columns:
            return pd.DataFrame()
        filtered = df[(df["pe_ratio"] > 0) & (df["pe_ratio"] <= max_pe) & (df["profit"] > 0)]
        return filtered.sort_values("pe_ratio", ascending=True).reset_index(drop=True)

    def get_company_profile(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch comprehensive company intelligence profile combining master metadata,
        latest fundamentals, time-series history, technicals (SMAs, returns), and volatility metrics.
        All fields are populated strictly from real database records without fabricating data.
        """
        sym = symbol.strip().upper()
        df_latest = self.market_analytics.get_latest_market_data()
        stock_row = df_latest[df_latest["symbol"] == sym] if not df_latest.empty and "symbol" in df_latest.columns else pd.DataFrame()

        # Fetch historical price observations
        df_history = self.market_analytics.get_historical_prices(symbol=sym, days=180)
        historical_metrics = self.market_analytics.calculate_stock_historical_metrics(sym)

        if not stock_row.empty:
            r = stock_row.iloc[0]
            close_val = float(r["close_price"]) if "close_price" in r and not pd.isna(r["close_price"]) else historical_metrics.get("current_price")
            change_val = float(r["change_percent"]) if "change_percent" in r and not pd.isna(r["change_percent"]) else historical_metrics.get("daily_change_pct")
            open_val = float(r["open_price"]) if "open_price" in r and not pd.isna(r["open_price"]) else None
            high_val = float(r["high_price"]) if "high_price" in r and not pd.isna(r["high_price"]) else None
            low_val = float(r["low_price"]) if "low_price" in r and not pd.isna(r["low_price"]) else None
            vol_val = int(r["volume"]) if "volume" in r and not pd.isna(r["volume"]) else 0
            mcap_val = float(r["market_cap"]) if "market_cap" in r and not pd.isna(r["market_cap"]) else None
            pe_val = float(r["pe_ratio"]) if "pe_ratio" in r and not pd.isna(r["pe_ratio"]) else None
            eps_val = float(r["eps"]) if "eps" in r and not pd.isna(r["eps"]) else None
            rev_val = float(r["revenue"]) if "revenue" in r and not pd.isna(r["revenue"]) else None
            profit_val = float(r["profit"]) if "profit" in r and not pd.isna(r["profit"]) else None
            debt_val = float(r["debt"]) if "debt" in r and not pd.isna(r["debt"]) else None

            profile = {
                "symbol": sym,
                "company_name": str(r.get("company_name", sym)),
                "sector": str(r.get("sector", "General")),
                "industry": str(r.get("industry", "General")),
                "current_price": close_val,
                "price": close_val,
                "close_price": close_val,
                "daily_change_pct": change_val,
                "change_percent": change_val,
                "open_price": open_val,
                "high_price": high_val,
                "low_price": low_val,
                "volume": vol_val,
                "market_cap": mcap_val,
                "pe_ratio": pe_val,
                "eps": eps_val,
                "revenue": rev_val,
                "profit": profit_val,
                "debt": debt_val,
                "return_1d_pct": change_val,
                "return_7d_pct": historical_metrics.get("return_7d_pct"),
                "return_30d_pct": historical_metrics.get("return_30d_pct"),
                "sma_7": historical_metrics.get("sma_7"),
                "sma_30": historical_metrics.get("sma_30"),
                "period_high": historical_metrics.get("period_high") or high_val,
                "period_low": historical_metrics.get("period_low") or low_val,
                "historical_volatility": historical_metrics.get("historical_volatility"),
                "volatility": historical_metrics.get("historical_volatility"),
                "observation_count": len(df_history),
                "history": df_history,
                "price_history": df_history,
                "status": "FOUND",
            }
        else:
            # Check if company exists in master table even if no current prices
            try:
                comp_df = self.db.query_to_dataframe("SELECT * FROM companies WHERE symbol = ?", (sym,))
            except Exception:
                comp_df = pd.DataFrame()

            if not comp_df.empty:
                r_comp = comp_df.iloc[0]
                company_name = str(r_comp.get("company_name", sym))
                sector = str(r_comp.get("sector", "General"))
                industry = str(r_comp.get("industry", "General"))
                status = "FOUND"
            else:
                company_name = sym
                sector = "General"
                industry = "General"
                status = "NOT_FOUND"

            profile = {
                "symbol": sym,
                "company_name": company_name,
                "sector": sector,
                "industry": industry,
                "current_price": historical_metrics.get("current_price"),
                "price": historical_metrics.get("current_price"),
                "close_price": historical_metrics.get("current_price"),
                "daily_change_pct": historical_metrics.get("daily_change_pct"),
                "change_percent": historical_metrics.get("daily_change_pct"),
                "open_price": None,
                "high_price": None,
                "low_price": None,
                "volume": 0,
                "market_cap": None,
                "pe_ratio": None,
                "eps": None,
                "revenue": None,
                "profit": None,
                "debt": None,
                "return_1d_pct": historical_metrics.get("daily_change_pct"),
                "return_7d_pct": historical_metrics.get("return_7d_pct"),
                "return_30d_pct": historical_metrics.get("return_30d_pct"),
                "sma_7": historical_metrics.get("sma_7"),
                "sma_30": historical_metrics.get("sma_30"),
                "period_high": historical_metrics.get("period_high"),
                "period_low": historical_metrics.get("period_low"),
                "historical_volatility": historical_metrics.get("historical_volatility"),
                "volatility": historical_metrics.get("historical_volatility"),
                "observation_count": len(df_history),
                "history": df_history,
                "price_history": df_history,
                "status": status,
            }

        return profile

    # Alias for backward compatibility
    get_stock_profile = get_company_profile
