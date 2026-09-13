"""
Validation Layer of ETL Pipeline.
Enforces schema validation, type integrity, and domain constraints using Pydantic V2 models.
Quarantines malformed records with detailed diagnostic logging.
"""

import logging
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, Type

import pandas as pd
from pydantic import BaseModel, Field, field_validator
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Validate")


class CompanyModel(BaseModel):
    """Pydantic validation model for company master records."""

    symbol: str = Field(..., min_length=1, max_length=20)
    company_name: str = Field(..., min_length=1, max_length=200)
    sector: Optional[str] = Field(default="General", max_length=100)
    industry: Optional[str] = Field(default="General", max_length=100)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Company symbol cannot be empty.")
        return cleaned


class StockPriceModel(BaseModel):
    """Pydantic validation model for daily stock price records."""

    symbol: str = Field(..., min_length=1, max_length=20)
    price_date: str
    open_price: Optional[float] = Field(default=None, ge=0)
    high_price: Optional[float] = Field(default=None, ge=0)
    low_price: Optional[float] = Field(default=None, ge=0)
    close_price: float = Field(..., gt=0)
    previous_close: Optional[float] = Field(default=None, ge=0)
    change_percent: Optional[float] = Field(default=None)
    volume: Optional[int] = Field(default=None, ge=0)

    @field_validator("price_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError(f"Invalid price_date '{v}'. Expected YYYY-MM-DD.")


class FundamentalModel(BaseModel):
    """Pydantic validation model for financial fundamentals records."""

    symbol: str = Field(..., min_length=1, max_length=20)
    recorded_date: str
    market_cap: Optional[float] = Field(default=None, ge=0)
    pe_ratio: Optional[float] = Field(default=None)
    eps: Optional[float] = Field(default=None)
    week_52_high: Optional[float] = Field(default=None, ge=0)
    week_52_low: Optional[float] = Field(default=None, ge=0)
    revenue: Optional[float] = Field(default=None)
    profit: Optional[float] = Field(default=None)
    debt: Optional[float] = Field(default=None, ge=0)

    @field_validator("recorded_date")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
            return v
        except ValueError:
            raise ValueError(f"Invalid recorded_date '{v}'. Expected YYYY-MM-DD.")


class MarketValidator:
    """Validates transformed dataframes against strict Pydantic schemas."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()

    @staticmethod
    def validate_dataframe(
        df: pd.DataFrame,
        model_cls: Type[BaseModel],
    ) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
        """
        Validate each row of DataFrame against given Pydantic model.
        Returns (valid_df, list_of_quarantined_errors).
        """
        if df.empty:
            return df, []

        valid_rows = []
        quarantine_errors = []

        records = df.to_dict(orient="records")
        for idx, row_dict in enumerate(records):
            # Clean out NaNs to None for Pydantic validation
            clean_dict = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}
            try:
                validated_model = model_cls(**clean_dict)
                valid_rows.append(validated_model.model_dump())
            except Exception as err:
                quarantine_errors.append({
                    "row_index": idx,
                    "record": row_dict,
                    "error": str(err),
                })

        valid_df = pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=df.columns)
        return valid_df, quarantine_errors

    def validate_all(
        self, transformed_data: Dict[str, pd.DataFrame]
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, List[Dict[str, Any]]]]:
        """Validate companies, stock prices, and fundamentals."""
        logger.info("================== [PHASE 3: VALIDATION] ==================")
        logger.info("Validating transformed data against Pydantic schemas...")

        validated_companies, comp_errs = self.validate_dataframe(
            transformed_data["companies"], CompanyModel
        )
        validated_prices, price_errs = self.validate_dataframe(
            transformed_data["prices"], StockPriceModel
        )
        validated_fundamentals, fund_errs = self.validate_dataframe(
            transformed_data["fundamentals"], FundamentalModel
        )

        all_errors = {
            "companies": comp_errs,
            "prices": price_errs,
            "fundamentals": fund_errs,
        }

        total_errs = len(comp_errs) + len(price_errs) + len(fund_errs)
        if total_errs > 0:
            logger.warning("Validation completed with %d quarantined records.", total_errs)
        else:
            logger.info("Schema validation successful: 0 errors detected across all entities.")

        return {
            "companies": validated_companies,
            "prices": validated_prices,
            "fundamentals": validated_fundamentals,
        }, all_errors
