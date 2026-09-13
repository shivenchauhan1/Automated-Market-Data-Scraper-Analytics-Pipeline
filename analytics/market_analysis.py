"""
Market Analytics Module.
Performs macroeconomic sector aggregation, market breadth calculations, historical volatility, and time-series metrics.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager

logger = logging.getLogger("MarketPipeline.MarketAnalytics")


class MarketAnalytics:
    """Computes market-wide, sector-level, and time-series financial indicators."""

    def __init__(self, config: Optional[Config] = None, db_manager: Optional[DatabaseManager] = None):
        self.config = config or get_config()
        self.db = db_manager or get_db_manager(self.config)

    def get_latest_market_data(self) -> pd.DataFrame:
        """Fetch latest stock prices merged with company metadata and fundamentals."""
        query = """
        SELECT 
            c.company_id,
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

    def get_historical_price_series(self, symbol: Optional[str] = None, limit_days: int = 90) -> pd.DataFrame:
        """
        Fetch time-series daily price history for a given symbol or all companies.
        """
        if symbol:
            query = """
            SELECT 
                c.symbol,
                c.company_name,
                c.sector,
                p.price_date,
                p.open_price,
                p.high_price,
                p.low_price,
                p.close_price,
                p.change_percent,
                p.volume
            FROM stock_prices p
            JOIN companies c ON p.company_id = c.company_id
            WHERE c.symbol = %s
            ORDER BY p.price_date ASC
            """ if self.db.active_engine == "mysql" else """
            SELECT 
                c.symbol,
                c.company_name,
                c.sector,
                p.price_date,
                p.open_price,
                p.high_price,
                p.low_price,
                p.close_price,
                p.change_percent,
                p.volume
            FROM stock_prices p
            JOIN companies c ON p.company_id = c.company_id
            WHERE c.symbol = ?
            ORDER BY p.price_date ASC
            """
            df = self.db.query_to_dataframe(query, (symbol.upper(),))
        else:
            query = """
            SELECT 
                c.symbol,
                c.company_name,
                c.sector,
                p.price_date,
                p.open_price,
                p.high_price,
                p.low_price,
                p.close_price,
                p.change_percent,
                p.volume
            FROM stock_prices p
            JOIN companies c ON p.company_id = c.company_id
            ORDER BY c.symbol ASC, p.price_date ASC
            """
            df = self.db.query_to_dataframe(query)

        return df

    def calculate_stock_historical_metrics(self, symbol: str) -> Dict[str, Any]:
        """
        Calculate stock-level historical metrics: 7D return, 30D return, SMA 7, SMA 30, High, Low, Volatility.
        Returns None for metrics where insufficient historical data exists.
        """
        df_history = self.get_historical_price_series(symbol=symbol)
        if df_history.empty:
            return {
                "symbol": symbol,
                "current_price": None,
                "daily_change_pct": None,
                "return_7d_pct": None,
                "return_30d_pct": None,
                "sma_7": None,
                "sma_30": None,
                "period_high": None,
                "period_low": None,
                "historical_volatility": None,
                "observation_count": 0,
            }

        prices = df_history["close_price"].tolist()
        changes = df_history["change_percent"].dropna().tolist()
        n_obs = len(prices)
        current_price = prices[-1]
        daily_change = changes[-1] if changes else None

        # 7-day return
        return_7d = None
        if n_obs >= 7:
            p_past = prices[-7]
            if p_past > 0:
                return_7d = round(((current_price - p_past) / p_past) * 100.0, 2)

        # 30-day return
        return_30d = None
        if n_obs >= 30:
            p_past = prices[-30]
            if p_past > 0:
                return_30d = round(((current_price - p_past) / p_past) * 100.0, 2)

        # 7-day SMA
        sma_7 = round(float(np.mean(prices[-7:])), 2) if n_obs >= 7 else round(float(np.mean(prices)), 2)

        # 30-day SMA
        sma_30 = round(float(np.mean(prices[-30:])), 2) if n_obs >= 30 else None

        # Period High / Low
        period_high = float(df_history["high_price"].max()) if not df_history["high_price"].isna().all() else current_price
        period_low = float(df_history["low_price"].min()) if not df_history["low_price"].isna().all() else current_price

        # Historical Volatility (standard deviation of daily return percentages)
        volatility = None
        if len(changes) >= 2:
            volatility = round(float(np.std(changes, ddof=1)), 2)

        return {
            "symbol": symbol,
            "current_price": current_price,
            "daily_change_pct": daily_change,
            "return_7d_pct": return_7d,
            "return_30d_pct": return_30d,
            "sma_7": sma_7,
            "sma_30": sma_30,
            "period_high": period_high,
            "period_low": period_low,
            "historical_volatility": volatility,
            "observation_count": n_obs,
        }

    def get_historical_prices(self, symbol: Optional[str] = None, days: int = 90) -> pd.DataFrame:
        """Convenience alias for get_historical_price_series."""
        return self.get_historical_price_series(symbol=symbol, limit_days=days)

    def calculate_moving_averages(self, df: pd.DataFrame, windows: List[int] = [7, 30]) -> pd.DataFrame:
        """
        Calculate simple moving averages (SMA) on close_price for specified rolling windows.
        """
        res_df = df.copy()
        if "close_price" not in res_df.columns:
            return res_df

        res_df = res_df.sort_values("price_date") if "price_date" in res_df.columns else res_df
        for w in windows:
            res_df[f"sma_{w}"] = res_df["close_price"].rolling(window=w, min_periods=1).mean().round(2)
        return res_df

    def calculate_time_series_returns(self, df: pd.DataFrame, windows: List[int] = [7, 30]) -> pd.DataFrame:
        """
        Calculate rolling returns (% change) over historical windows.
        """
        res_df = df.copy()
        if "close_price" not in res_df.columns:
            return res_df

        res_df = res_df.sort_values("price_date") if "price_date" in res_df.columns else res_df
        for w in windows:
            res_df[f"return_{w}d_pct"] = (
                (res_df["close_price"] - res_df["close_price"].shift(w)) / res_df["close_price"].shift(w) * 100.0
            ).round(2)
        return res_df

    def calculate_historical_volatility(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Compute annualized or period historical volatility (standard deviation of returns).
        """
        if df is None:
            df = self.get_latest_market_data()
        if df.empty or "change_percent" not in df.columns:
            return pd.DataFrame(columns=["symbol", "historical_volatility"])

        vol_df = df.groupby("symbol")["change_percent"].std().reset_index()
        vol_df.columns = ["symbol", "historical_volatility"]
        return vol_df

    def calculate_sector_volatility(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Compute standard deviation of returns across companies grouped by sector.
        """
        if df is None:
            df = self.get_latest_market_data()
        if df.empty or "sector" not in df.columns or "change_percent" not in df.columns:
            return pd.DataFrame(columns=["sector", "return_std_dev", "company_count"])

        sec_vols = []
        for sector, group in df.groupby("sector"):
            std_dev = group["change_percent"].std() if len(group) > 1 else 0.0
            sec_vols.append({
                "sector": sector,
                "return_std_dev": round(float(std_dev), 2) if not pd.isna(std_dev) else 0.0,
                "company_count": len(group),
            })
        return pd.DataFrame(sec_vols).sort_values("return_std_dev", ascending=False).reset_index(drop=True)

    def calculate_sector_performance(self, df: Optional[pd.DataFrame] = None) -> pd.DataFrame:
        """
        Calculate aggregated performance metrics grouped by sector, including sector volatility.
        """
        if df is None:
            df = self.get_latest_market_data()

        if df.empty:
            return pd.DataFrame(columns=["sector", "company_count", "avg_return_pct", "sector_volatility", "total_market_cap_cr", "total_volume", "advancers", "decliners"])

        sector_stats = []
        for sector, group in df.groupby("sector"):
            avg_return = group["change_percent"].mean()
            volatility = group["change_percent"].std() if len(group) > 1 else 0.0
            total_mcap = group["market_cap"].sum() if "market_cap" in group.columns else 0.0
            total_vol = group["volume"].sum() if "volume" in group.columns else 0
            advancers = (group["change_percent"] > 0).sum()
            decliners = (group["change_percent"] < 0).sum()
            avg_pe = group["pe_ratio"].mean() if "pe_ratio" in group.columns else None

            sector_stats.append({
                "sector": sector,
                "company_count": len(group),
                "avg_return_pct": round(float(avg_return), 2) if not pd.isna(avg_return) else 0.0,
                "sector_volatility": round(float(volatility), 2) if not pd.isna(volatility) else 0.0,
                "total_market_cap_cr": round(float(total_mcap), 2) if not pd.isna(total_mcap) else 0.0,
                "total_volume": int(total_vol) if not pd.isna(total_vol) else 0,
                "avg_pe_ratio": round(float(avg_pe), 2) if avg_pe is not None and not pd.isna(avg_pe) else None,
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
            return {
                "advancers": 0,
                "decliners": 0,
                "advances": 0,
                "declines": 0,
                "unchanged": 0,
                "ad_ratio": 1.0,
                "total_tracked": 0,
                "market_sentiment": "Neutral",
            }

        advancers = int((df["change_percent"] > 0).sum())
        decliners = int((df["change_percent"] < 0).sum())
        unchanged = int((df["change_percent"] == 0).sum())
        total = len(df)
        ad_ratio = round(advancers / decliners, 2) if decliners > 0 else (float(advancers) if advancers > 0 else 1.0)

        return {
            "advancers": advancers,
            "decliners": decliners,
            "advances": advancers,
            "declines": decliners,
            "unchanged": unchanged,
            "ad_ratio": ad_ratio,
            "total_tracked": total,
            "market_sentiment": "Bullish" if advancers > decliners else ("Bearish" if decliners > advancers else "Neutral"),
        }

    def get_company_profile(self, symbol: str) -> Dict[str, Any]:
        """Fetch full company profile delegating to KPIAnalytics."""
        from analytics.kpi_analysis import KPIAnalytics
        kpi = KPIAnalytics(self.config, self.db)
        return kpi.get_company_profile(symbol)


def run_analysis(df: Optional[pd.DataFrame] = None, db: Optional[DatabaseManager] = None, config: Optional[Config] = None) -> Dict[str, Any]:
    """Execute complete analytics suite."""
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

    best_sector = sector_df.iloc[0]["sector"] if not sector_df.empty else "N/A"
    worst_sector = sector_df.iloc[-1]["sector"] if not sector_df.empty else "N/A"

    return {
        "breadth": breadth,
        "sector_performance": sector_df,
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "kpis": kpis,
        "best_sector": best_sector,
        "worst_sector": worst_sector,
        "market_df": df,
    }
