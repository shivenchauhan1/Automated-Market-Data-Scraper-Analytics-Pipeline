"""
Data Quality Engine & Metrics Calculator.
Evaluates data completeness, validity, uniqueness, and schema compliance to produce a deterministic, documented Data Quality Score.
"""

import logging
from typing import Any, Dict, List, Optional
import pandas as pd

logger = logging.getLogger("MarketPipeline.DataQuality")


class DataQualityReport:
    """Container for data quality telemetry and score breakdown."""

    def __init__(
        self,
        records_extracted: int = 0,
        records_transformed: int = 0,
        records_valid: int = 0,
        records_invalid: int = 0,
        records_quarantined: int = 0,
        duplicate_records: int = 0,
        missing_values: int = 0,
        total_expected_cells: int = 0,
        validation_errors: int = 0,
        quality_score: float = 100.0,
        score_breakdown: Optional[Dict[str, float]] = None,
    ):
        self.records_extracted = records_extracted
        self.records_transformed = records_transformed
        self.records_valid = records_valid
        self.records_invalid = records_invalid
        self.records_quarantined = records_quarantined
        self.duplicate_records = duplicate_records
        self.missing_values = missing_values
        self.total_expected_cells = total_expected_cells
        self.validation_errors = validation_errors
        self.quality_score = round(quality_score, 2)
        self.score_breakdown = score_breakdown or {}

    @property
    def grade(self) -> str:
        """Categorical grade based on quality score."""
        if self.quality_score >= 90.0:
            return "A"
        elif self.quality_score >= 80.0:
            return "B"
        elif self.quality_score >= 70.0:
            return "C"
        elif self.quality_score >= 60.0:
            return "D"
        return "F"

    @property
    def passed(self) -> bool:
        """True if score meets passing threshold (>= 75%)."""
        return self.quality_score >= 75.0

    @property
    def metrics(self) -> "DataQualityReport":
        """Self reference for backward compatibility with nested metrics accesses."""
        return self

    def to_dict(self) -> Dict[str, Any]:
        """Convert report to dictionary format."""
        return {
            "records_extracted": self.records_extracted,
            "records_transformed": self.records_transformed,
            "records_valid": self.records_valid,
            "records_invalid": self.records_invalid,
            "records_quarantined": self.records_quarantined,
            "duplicate_records": self.duplicate_records,
            "missing_values": self.missing_values,
            "total_expected_cells": self.total_expected_cells,
            "validation_errors": self.validation_errors,
            "data_quality_score": self.quality_score,
            "grade": self.grade,
            "passed": self.passed,
            "score_breakdown": self.score_breakdown,
        }


class DataQualityManager:
    """Calculates data quality metrics and score using a weighted multi-factor formula."""

    # Weights for Data Quality Score components (Sum = 1.0)
    WEIGHT_VALIDITY = 0.40      # Pydantic schema validation success rate
    WEIGHT_COMPLETENESS = 0.30  # Percentage of non-null required cells
    WEIGHT_UNIQUENESS = 0.20    # Absence of redundant duplicate entries
    WEIGHT_CONFORMANCE = 0.10   # Type casting and domain constraint conformance

    @classmethod
    def evaluate(
        cls,
        raw_payload: Dict[str, Any],
        transformed_data: Dict[str, pd.DataFrame],
        validated_data: Dict[str, pd.DataFrame],
        quarantine_errors: Dict[str, List[Dict[str, Any]]],
    ) -> DataQualityReport:
        """
        Evaluate end-to-end data quality and compute quality score.
        """
        raw_stocks = raw_payload.get("market", raw_payload.get("stocks", []))
        raw_funds = raw_payload.get("fundamentals", [])
        total_extracted = len(raw_stocks) + len(raw_funds)

        df_prices = transformed_data.get("prices", pd.DataFrame())
        df_funds = transformed_data.get("fundamentals", pd.DataFrame())
        total_transformed = len(df_prices) + len(df_funds)

        valid_prices = validated_data.get("prices", pd.DataFrame())
        valid_funds = validated_data.get("fundamentals", pd.DataFrame())
        total_valid = len(valid_prices) + len(valid_funds)

        total_invalid = sum(len(errs) for errs in quarantine_errors.values())
        total_quarantined = total_invalid

        # Duplicate calculation
        duplicate_stocks = max(0, len(raw_stocks) - len(df_prices))
        duplicate_funds = max(0, len(raw_funds) - len(df_funds))
        total_duplicates = duplicate_stocks + duplicate_funds

        # Missing values in key fields (symbol, close_price, pe_ratio)
        missing_count = 0
        total_cells = 0
        for df in [df_prices, df_funds]:
            if not df.empty:
                missing_count += int(df.isna().sum().sum())
                total_cells += int(df.shape[0] * df.shape[1])

        total_cells = max(total_cells, 1)

        # 1. Validity Score (S_valid): Valid records / Total records
        if total_transformed > 0:
            s_valid = (total_valid / (total_valid + total_invalid)) * 100.0
        else:
            s_valid = 100.0

        # 2. Completeness Score (S_complete): (1 - missing_cells / total_cells)
        s_complete = max(0.0, (1.0 - (missing_count / total_cells)) * 100.0)

        # 3. Uniqueness Score (S_unique): (1 - duplicates / extracted)
        if total_extracted > 0:
            s_unique = max(0.0, (1.0 - (total_duplicates / total_extracted)) * 100.0)
        else:
            s_unique = 100.0

        # 4. Conformance Score (S_conformance): based on fatal type violations
        s_conformance = max(0.0, 100.0 - (total_invalid * 5.0))

        # Weighted composite score
        composite_score = (
            (cls.WEIGHT_VALIDITY * s_valid)
            + (cls.WEIGHT_COMPLETENESS * s_complete)
            + (cls.WEIGHT_UNIQUENESS * s_unique)
            + (cls.WEIGHT_CONFORMANCE * s_conformance)
        )
        composite_score = max(0.0, min(100.0, composite_score))

        grade = "A" if composite_score >= 90.0 else ("B" if composite_score >= 80.0 else ("C" if composite_score >= 70.0 else "D"))

        breakdown = {
            "validity_score": round(s_valid, 2),
            "completeness_score": round(s_complete, 2),
            "uniqueness_score": round(s_unique, 2),
            "conformance_score": round(s_conformance, 2),
            "grade": grade,
        }

        logger.info("Data Quality Score calculated: %.2f%% (Breakdown: %s)", composite_score, breakdown)

        return DataQualityReport(
            records_extracted=total_extracted,
            records_transformed=total_transformed,
            records_valid=total_valid,
            records_invalid=total_invalid,
            records_quarantined=total_quarantined,
            duplicate_records=total_duplicates,
            missing_values=missing_count,
            total_expected_cells=total_cells,
            validation_errors=total_invalid,
            quality_score=composite_score,
            score_breakdown=breakdown,
        )


def compute_data_quality(
    raw_payload: Dict[str, Any] = None,
    transformed_data: Dict[str, pd.DataFrame] = None,
    validated_data: Dict[str, pd.DataFrame] = None,
    quarantine_errors: Dict[str, List[Dict[str, Any]]] = None,
    config: Optional[Any] = None,
    **kwargs,
) -> DataQualityReport:
    """Functional helper for data quality evaluation."""
    raw = raw_payload if raw_payload is not None else kwargs.get("raw_data", {})
    errors = quarantine_errors if quarantine_errors is not None else kwargs.get("errors", {})
    return DataQualityManager.evaluate(raw, transformed_data or {}, validated_data or {}, errors or {})

