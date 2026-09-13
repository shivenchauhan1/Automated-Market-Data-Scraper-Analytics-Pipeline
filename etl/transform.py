"""
Transform Layer of ETL Pipeline.
Cleans, normalizes, and casts raw scraped financial strings into typed, database-ready dictionaries and DataFrames.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Transform")


def clean_price(value: Any) -> Optional[float]:
    """
    Convert price strings like '₹1,450.50', '$2,980.00', '1450.50' to float.
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value) if not np.isnan(value) else None

    value_str = str(value).strip()
    if value_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
        return None

    cleaned = re.sub(r"[₹$,\s]", "", value_str)
    try:
        return float(cleaned)
    except ValueError:
        logger.debug("Failed to parse price float from: '%s'", value_str)
        return None


def clean_percentage(value: Any) -> Optional[float]:
    """
    Convert percentage strings like '+1.25%', '-0.45%', '1.25' to float.
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value) if not np.isnan(value) else None

    value_str = str(value).strip()
    if value_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
        return None

    cleaned = re.sub(r"[%,\s]", "", value_str)
    try:
        return float(cleaned)
    except ValueError:
        logger.debug("Failed to parse percentage float from: '%s'", value_str)
        return None


def clean_volume(value: Any) -> Optional[int]:
    """
    Convert volume strings like '4.2M', '500K', '1.2B', '2,340' to integer.
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return int(value) if not np.isnan(value) else None

    val_str = str(value).strip().upper()
    if val_str in ["N/A", "NA", "-", "--", "NULL", ""]:
        return None

    multiplier = 1
    if val_str.endswith("B"):
        multiplier = 1_000_000_000
        val_str = val_str[:-1]
    elif val_str.endswith("M"):
        multiplier = 1_000_000
        val_str = val_str[:-1]
    elif val_str.endswith("K"):
        multiplier = 1_000
        val_str = val_str[:-1]
    elif val_str.endswith("CR"):
        multiplier = 10_000_000
        val_str = val_str[:-2]

    cleaned = re.sub(r"[,₹$\s]", "", val_str)
    try:
        return int(float(cleaned) * multiplier)
    except ValueError:
        logger.debug("Failed to parse volume integer from: '%s'", val_str)
        return None


def clean_market_cap_or_financial(value: Any) -> Optional[float]:
    """
    Convert financial figures like '₹20,15,400 Cr', '₹9,80,000 Cr' to numeric value (in Crores).
    """
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value) if not np.isnan(value) else None

    val_str = str(value).strip().upper()
    if val_str in ["N/A", "NA", "-", "--", "NULL", ""]:
        return None

    is_negative = "-" in val_str
    cleaned = re.sub(r"[₹$,\sCRcrTtBbMm-]", "", val_str)
    try:
        num = float(cleaned)
        return -num if is_negative else num
    except ValueError:
        logger.debug("Failed to parse financial float from: '%s'", val_str)
        return None


def clean_ratio(value: Any) -> Optional[float]:
    """Convert financial ratio strings like '28.4', '105.20' to float."""
    if value is None or pd.isna(value):
        return None
    if isinstance(value, (int, float)):
        return float(value) if not np.isnan(value) else None

    val_str = str(value).strip()
    if val_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
        return None

    cleaned = re.sub(r"[,\s]", "", val_str)
    try:
        return float(cleaned)
    except ValueError:
        return None


def transform_stock(record: Dict[str, Any]) -> Dict[str, Any]:
    """Turn messy stock record into database-ready dictionary."""
    symbol = str(record.get("symbol", "")).strip().upper()
    price = clean_price(record.get("price"))
    prev_close = clean_price(record.get("previous_close")) or price
    open_price = clean_price(record.get("open_price")) or prev_close
    high_price = clean_price(record.get("high_price")) or max(price or 0, open_price or 0)
    low_price = clean_price(record.get("low_price")) or min(price or 0, open_price or 0)
    change_pct = clean_percentage(record.get("change_percent")) or 0.0
    vol = clean_volume(record.get("volume")) or 0

    return {
        "symbol": symbol,
        "company_name": str(record.get("company_name", symbol)).strip(),
        "sector": str(record.get("sector", "General")).strip(),
        "industry": str(record.get("industry", "General")).strip(),
        "price_date": datetime.now().strftime("%Y-%m-%d"),
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": price,
        "previous_close": prev_close,
        "change_percent": change_pct,
        "volume": vol,
    }


def transform_fundamental(record: Dict[str, Any]) -> Dict[str, Any]:
    """Turn messy fundamental record into database-ready dictionary."""
    symbol = str(record.get("symbol", "")).strip().upper()
    return {
        "symbol": symbol,
        "market_cap": clean_market_cap_or_financial(record.get("market_cap")),
        "pe_ratio": clean_ratio(record.get("pe_ratio")),
        "eps": clean_ratio(record.get("eps")),
        "revenue": clean_market_cap_or_financial(record.get("revenue")),
        "profit": clean_market_cap_or_financial(record.get("profit")),
        "debt": clean_market_cap_or_financial(record.get("debt")),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


class MarketTransformer:
    """Cleans currency, percentage, and ratio strings into standardized DataFrames."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.clean_price = clean_price
        self.clean_percentage = clean_percentage
        self.clean_volume = clean_volume
        self.clean_market_cap_or_financial = clean_market_cap_or_financial
        self.clean_ratio = clean_ratio

    def transform_stocks(self, raw_stocks: List[Dict[str, Any]]) -> pd.DataFrame:
        """Transform raw stock list into a clean Pandas DataFrame."""
        if not raw_stocks:
            return pd.DataFrame()
        transformed = [transform_stock(r) for r in raw_stocks if "symbol" in r]
        df = pd.DataFrame(transformed)
        return df.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)

    def transform_fundamentals(self, raw_fundamentals: List[Dict[str, Any]]) -> pd.DataFrame:
        """Transform raw fundamentals list into a clean Pandas DataFrame."""
        if not raw_fundamentals:
            return pd.DataFrame()
        transformed = [transform_fundamental(r) for r in raw_fundamentals if "symbol" in r]
        df = pd.DataFrame(transformed)
        return df.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)

    def transform_all(self, raw_payload: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        """Execute all transformation steps."""
        logger.info("================== [PHASE 2: TRANSFORMATION] ==================")
        logger.info("Transforming raw market data...")

        stocks_raw = raw_payload.get("market", raw_payload.get("stocks", []))
        funds_raw = raw_payload.get("fundamentals", [])

        df_stocks = self.transform_stocks(stocks_raw)
        df_fundamentals = self.transform_fundamentals(funds_raw)
        df_companies = df_stocks[["symbol", "company_name", "sector", "industry"]].copy() if not df_stocks.empty else pd.DataFrame()

        logger.info(
            "Transformation complete: %d companies, %d price records, %d fundamental records.",
            len(df_companies),
            len(df_stocks),
            len(df_fundamentals),
        )

        return {
            "companies": df_companies,
            "prices": df_stocks,
            "fundamentals": df_fundamentals,
        }


def transform(raw_data: Dict[str, Any], config: Optional[Config] = None) -> Dict[str, pd.DataFrame]:
    """Functional helper for transformation."""
    transformer = MarketTransformer(config)
    return transformer.transform_all(raw_data)
