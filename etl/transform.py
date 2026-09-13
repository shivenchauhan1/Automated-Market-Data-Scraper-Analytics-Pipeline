"""
Transform Layer of ETL Pipeline.
Cleans, normalizes, and enriches raw scraped financial strings into typed, structured Pandas DataFrames.
"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Transform")


class MarketTransformer:
    """Cleans currency, percentage, and ratio strings into standardized numeric structures."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()

    @staticmethod
    def clean_price(val: Any) -> Optional[float]:
        """
        Convert price strings like '₹1,450.50', '$2,980.00', '1450.50' to float.
        """
        if val is None or pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return float(val) if not np.isnan(val) else None

        val_str = str(val).strip()
        if val_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
            return None

        # Strip currency symbols, commas, spaces
        cleaned = re.sub(r"[₹$,\s]", "", val_str)
        try:
            return float(cleaned)
        except ValueError:
            logger.debug("Failed to parse price float from: '%s'", val_str)
            return None

    @staticmethod
    def clean_percentage(val: Any) -> Optional[float]:
        """
        Convert percentage strings like '+1.25%', '-0.45%', '1.25' to float.
        """
        if val is None or pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return float(val) if not np.isnan(val) else None

        val_str = str(val).strip()
        if val_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
            return None

        # Strip % symbol, commas, spaces
        cleaned = re.sub(r"[%,\s]", "", val_str)
        try:
            return float(cleaned)
        except ValueError:
            logger.debug("Failed to parse percentage float from: '%s'", val_str)
            return None

    @staticmethod
    def clean_volume(val: Any) -> Optional[int]:
        """
        Convert volume strings like '4.2M', '500K', '1.2B', '2,340' to integer.
        """
        if val is None or pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return int(val) if not np.isnan(val) else None

        val_str = str(val).strip().upper()
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

    @staticmethod
    def clean_market_cap_or_financial(val: Any) -> Optional[float]:
        """
        Convert financial figures like '₹20,15,400 Cr', '₹9,80,000 Cr', '$1.5B' to numeric value (in Crores).
        """
        if val is None or pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return float(val) if not np.isnan(val) else None

        val_str = str(val).strip().upper()
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

    @staticmethod
    def clean_ratio(val: Any) -> Optional[float]:
        """Convert financial ratio strings like '28.4', '105.20' to float."""
        if val is None or pd.isna(val):
            return None
        if isinstance(val, (int, float)):
            return float(val) if not np.isnan(val) else None

        val_str = str(val).strip()
        if val_str.upper() in ["N/A", "NA", "-", "--", "NULL", ""]:
            return None

        cleaned = re.sub(r"[,\s]", "", val_str)
        try:
            return float(cleaned)
        except ValueError:
            return None

    def transform_stocks(self, raw_stocks: List[Dict[str, Any]]) -> pd.DataFrame:
        """Transform raw stock list into a clean Pandas DataFrame."""
        if not raw_stocks:
            return pd.DataFrame()

        df = pd.DataFrame(raw_stocks)

        # Ensure default string columns exist
        if "symbol" not in df.columns:
            return pd.DataFrame()

        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()

        if "company_name" not in df.columns:
            df["company_name"] = df["symbol"]
        else:
            df["company_name"] = df["company_name"].astype(str).str.strip()

        if "sector" not in df.columns:
            df["sector"] = "General"
        else:
            df["sector"] = df["sector"].astype(str).str.strip()

        if "industry" not in df.columns:
            df["industry"] = "General"
        else:
            df["industry"] = df["industry"].astype(str).str.strip()

        # Clean numeric fields
        df["close_price"] = df["price"].apply(self.clean_price)
        if "previous_close" in df.columns:
            df["previous_close"] = df["previous_close"].apply(self.clean_price)
        else:
            df["previous_close"] = df["close_price"]

        if "open_price" in df.columns:
            df["open_price"] = df["open_price"].apply(self.clean_price)
        else:
            df["open_price"] = df["previous_close"]

        if "high_price" in df.columns:
            df["high_price"] = df["high_price"].apply(self.clean_price)
        else:
            df["high_price"] = df["close_price"]

        if "low_price" in df.columns:
            df["low_price"] = df["low_price"].apply(self.clean_price)
        else:
            df["low_price"] = df["close_price"]

        # Handle high/low sanity
        df["high_price"] = df[["high_price", "close_price", "open_price"]].max(axis=1)
        df["low_price"] = df[["low_price", "close_price", "open_price"]].min(axis=1)

        df["change_percent"] = df["change_percent"].apply(self.clean_percentage) if "change_percent" in df.columns else 0.0
        df["volume"] = df["volume"].apply(self.clean_volume) if "volume" in df.columns else 0
        df["price_date"] = datetime.now().strftime("%Y-%m-%d")

        # Deduplicate on symbol keeping last scraped
        df = df.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)
        return df

    def transform_fundamentals(self, raw_fundamentals: List[Dict[str, Any]]) -> pd.DataFrame:
        """Transform raw fundamentals list into a clean Pandas DataFrame."""
        if not raw_fundamentals:
            return pd.DataFrame()

        df = pd.DataFrame(raw_fundamentals)
        if "symbol" not in df.columns:
            return pd.DataFrame()

        df["symbol"] = df["symbol"].astype(str).str.strip().str.upper()
        df["market_cap"] = df["market_cap"].apply(self.clean_market_cap_or_financial) if "market_cap" in df.columns else None
        df["pe_ratio"] = df["pe_ratio"].apply(self.clean_ratio) if "pe_ratio" in df.columns else None
        df["eps"] = df["eps"].apply(self.clean_ratio) if "eps" in df.columns else None
        df["week_52_high"] = df["week_52_high"].apply(self.clean_price) if "week_52_high" in df.columns else None
        df["week_52_low"] = df["week_52_low"].apply(self.clean_price) if "week_52_low" in df.columns else None
        df["revenue"] = df["revenue"].apply(self.clean_market_cap_or_financial) if "revenue" in df.columns else None
        df["profit"] = df["profit"].apply(self.clean_market_cap_or_financial) if "profit" in df.columns else None
        df["debt"] = df["debt"].apply(self.clean_market_cap_or_financial) if "debt" in df.columns else None
        df["recorded_date"] = df["recorded_date"] if "recorded_date" in df.columns else datetime.now().strftime("%Y-%m-%d")

        df = df.drop_duplicates(subset=["symbol"], keep="last").reset_index(drop=True)
        return df

    def transform_all(self, raw_payload: Dict[str, Any]) -> Dict[str, pd.DataFrame]:
        """Execute all transformation steps."""
        logger.info("================== [PHASE 2: TRANSFORMATION] ==================")
        logger.info("Transforming raw market data...")

        df_stocks = self.transform_stocks(raw_payload.get("stocks", []))
        df_fundamentals = self.transform_fundamentals(raw_payload.get("fundamentals", []))

        # Separate into normalized entity tables
        df_companies = df_stocks[["symbol", "company_name", "sector", "industry"]].copy()

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
