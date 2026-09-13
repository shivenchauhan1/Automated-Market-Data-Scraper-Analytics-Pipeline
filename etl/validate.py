"""
Validation Layer of ETL Pipeline.
Enforces schema validation, type integrity, and domain constraints using Pydantic V2 models.
Quarantines malformed records to data/quarantine/invalid_records.json with taxonomy details (timestamp, source, field, error_type).
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import pandas as pd
from pydantic import BaseModel, Field, ValidationError, field_validator
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Validate")


class StockRecord(BaseModel):
    """Pydantic validation model for daily stock price records."""

    symbol: str = Field(..., min_length=1, max_length=20)
    company_name: Optional[str] = Field(default="")
    sector: Optional[str] = Field(default="General")
    industry: Optional[str] = Field(default="General")
    price_date: Optional[str] = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    open_price: Optional[float] = Field(default=None, ge=0)
    high_price: Optional[float] = Field(default=None, ge=0)
    low_price: Optional[float] = Field(default=None, ge=0)
    close_price: float = Field(..., ge=0)
    change_percent: float = Field(default=0.0)
    volume: Optional[int] = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Stock symbol cannot be empty.")
        return cleaned


class FundamentalRecord(BaseModel):
    """Pydantic validation model for financial fundamentals records."""

    symbol: str = Field(..., min_length=1, max_length=20)
    updated_at: Optional[str] = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    market_cap: Optional[float] = Field(default=None, ge=0)
    pe_ratio: Optional[float] = Field(default=None)
    eps: Optional[float] = Field(default=None)
    revenue: Optional[float] = Field(default=None)
    profit: Optional[float] = Field(default=None)
    debt: Optional[float] = Field(default=None, ge=0)

    @field_validator("symbol")
    @classmethod
    def validate_symbol(cls, v: str) -> str:
        cleaned = v.strip().upper()
        if not cleaned:
            raise ValueError("Fundamental symbol cannot be empty.")
        return cleaned


class CompanyRecord(BaseModel):
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


# Backward compatibility aliases
StockPriceModel = StockRecord
FundamentalModel = FundamentalRecord
CompanyModel = CompanyRecord


class MarketValidator:
    """Validates transformed data against strict Pydantic schemas and manages quarantined records."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.quarantine_dir = self.config.DATA_QUARANTINE_DIR

    def validate_dataframe(
        self,
        df: pd.DataFrame,
        model_cls: Type[BaseModel],
        source: str = "etl_pipeline",
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
            clean_dict = {k: (None if pd.isna(v) else v) for k, v in row_dict.items()}
            try:
                validated_model = model_cls(**clean_dict)
                valid_rows.append(validated_model.model_dump())
            except ValidationError as val_err:
                error_details = val_err.errors()[0] if val_err.errors() else {}
                field_name = str(error_details.get("loc", ["unknown"])[0])
                msg = error_details.get("msg", str(val_err))
                
                quarantine_errors.append({
                    "timestamp": datetime.now().isoformat(),
                    "source": source,
                    "record": row_dict,
                    "validation_error": msg,
                    "field": field_name,
                    "error_type": "validation_error",
                    "row_index": idx,
                })
            except Exception as err:
                quarantine_errors.append({
                    "timestamp": datetime.now().isoformat(),
                    "source": source,
                    "record": row_dict,
                    "validation_error": str(err),
                    "field": "general",
                    "error_type": "type_error",
                    "row_index": idx,
                })

        valid_df = pd.DataFrame(valid_rows) if valid_rows else pd.DataFrame(columns=df.columns)
        return valid_df, quarantine_errors

    def quarantine_invalid_records(self, invalid_records: Dict[str, List[Dict[str, Any]]]) -> Optional[Path]:
        """Write quarantined records to data/quarantine/invalid_records.json."""
        all_quarantine_entries = []
        for entity_type, errs in invalid_records.items():
            for err in errs:
                entry = dict(err)
                entry["entity"] = entity_type
                all_quarantine_entries.append(entry)

        if not all_quarantine_entries:
            return None

        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        filepath = self.quarantine_dir / "invalid_records.json"

        quarantine_payload = {
            "last_quarantined_at": datetime.now().isoformat(),
            "total_quarantined_records": len(all_quarantine_entries),
            "records": all_quarantine_entries,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(quarantine_payload, f, indent=2, ensure_ascii=False)

        logger.warning("Quarantined %d malformed records to: %s", len(all_quarantine_entries), filepath)
        return filepath

    def validate_all(
        self, transformed_data: Dict[str, pd.DataFrame]
    ) -> Tuple[Dict[str, pd.DataFrame], Dict[str, List[Dict[str, Any]]]]:
        """Validate companies, stock prices, and fundamentals."""
        logger.info("================== [PHASE 3: VALIDATION] ==================")
        logger.info("Validating transformed data against Pydantic schemas...")

        validated_companies, comp_errs = self.validate_dataframe(
            transformed_data.get("companies", pd.DataFrame()), CompanyRecord, source="companies_transform"
        )
        validated_prices, price_errs = self.validate_dataframe(
            transformed_data.get("prices", pd.DataFrame()), StockRecord, source="prices_transform"
        )
        validated_fundamentals, fund_errs = self.validate_dataframe(
            transformed_data.get("fundamentals", pd.DataFrame()), FundamentalRecord, source="fundamentals_transform"
        )

        all_errors = {
            "companies": comp_errs,
            "prices": price_errs,
            "fundamentals": fund_errs,
        }

        self.quarantine_invalid_records(all_errors)

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


def validate(transformed_data: Dict[str, pd.DataFrame], config: Optional[Config] = None):
    """Functional helper for validation."""
    validator = MarketValidator(config)
    return validator.validate_all(transformed_data)


def quarantine(invalid_records: Dict[str, List[Dict[str, Any]]], config: Optional[Config] = None) -> Optional[Path]:
    """Functional helper for record quarantining."""
    validator = MarketValidator(config)
    return validator.quarantine_invalid_records(invalid_records)
