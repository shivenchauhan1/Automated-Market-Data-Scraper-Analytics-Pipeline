"""
Load Layer of ETL Pipeline.
Loads validated dataframes into MySQL / SQLite relational tables with foreign key resolution, upserts, and telemetry tracking.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from config.config import Config, get_config
from database.db_connection import DatabaseManager, get_db_manager

logger = logging.getLogger("MarketPipeline.Load")


class MarketLoader:
    """Loads validated entities into relational database tables and exports processed files."""

    def __init__(self, config: Optional[Config] = None, db_manager: Optional[DatabaseManager] = None):
        self.config = config or get_config()
        self.db = db_manager or get_db_manager(self.config)

    def load_companies(self, df_companies: pd.DataFrame) -> Dict[str, int]:
        """
        Upsert companies into companies table and return symbol -> company_id lookup dict.
        """
        if df_companies.empty:
            return {}

        symbol_to_id: Dict[str, int] = {}
        is_sqlite = (self.db.active_engine == "sqlite")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df_companies.iterrows():
                symbol = row["symbol"]
                name = row["company_name"]
                sector = row.get("sector", "General")
                industry = row.get("industry", "General")

                if is_sqlite:
                    cursor.execute(
                        """
                        INSERT INTO companies (symbol, company_name, sector, industry, updated_at)
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(symbol) DO UPDATE SET
                            company_name=excluded.company_name,
                            sector=excluded.sector,
                            industry=excluded.industry,
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (symbol, name, sector, industry),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO companies (symbol, company_name, sector, industry)
                        VALUES (%s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            company_name=VALUES(company_name),
                            sector=VALUES(sector),
                            industry=VALUES(industry),
                            updated_at=CURRENT_TIMESTAMP
                        """,
                        (symbol, name, sector, industry),
                    )

            conn.commit()

            # Retrieve all company mappings
            cursor.execute("SELECT company_id, symbol FROM companies")
            rows = cursor.fetchall()
            for r in rows:
                if is_sqlite:
                    symbol_to_id[r["symbol"]] = r["company_id"]
                else:
                    symbol_to_id[r["symbol"]] = r["company_id"]

        logger.info("Loaded/Upserted %d companies into master table.", len(df_companies))
        return symbol_to_id

    def load_stock_prices(self, df_prices: pd.DataFrame, symbol_to_id: Dict[str, int]) -> int:
        """Upsert daily stock price records into stock_prices table."""
        if df_prices.empty:
            return 0

        inserted_count = 0
        is_sqlite = (self.db.active_engine == "sqlite")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df_prices.iterrows():
                symbol = row["symbol"]
                company_id = symbol_to_id.get(symbol)
                if not company_id:
                    continue

                price_date = row["price_date"]
                open_p = row.get("open_price")
                high_p = row.get("high_price")
                low_p = row.get("low_price")
                close_p = row["close_price"]
                prev_p = row.get("previous_close")
                chg_pct = row.get("change_percent")
                vol = row.get("volume")

                if is_sqlite:
                    cursor.execute(
                        """
                        INSERT INTO stock_prices (
                            company_id, price_date, open_price, high_price, low_price,
                            close_price, previous_close, change_percent, volume
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_id, price_date) DO UPDATE SET
                            open_price=excluded.open_price,
                            high_price=excluded.high_price,
                            low_price=excluded.low_price,
                            close_price=excluded.close_price,
                            previous_close=excluded.previous_close,
                            change_percent=excluded.change_percent,
                            volume=excluded.volume
                        """,
                        (company_id, price_date, open_p, high_p, low_p, close_p, prev_p, chg_pct, vol),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO stock_prices (
                            company_id, price_date, open_price, high_price, low_price,
                            close_price, previous_close, change_percent, volume
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            open_price=VALUES(open_price),
                            high_price=VALUES(high_price),
                            low_price=VALUES(low_price),
                            close_price=VALUES(close_price),
                            previous_close=VALUES(previous_close),
                            change_percent=VALUES(change_percent),
                            volume=VALUES(volume)
                        """,
                        (company_id, price_date, open_p, high_p, low_p, close_p, prev_p, chg_pct, vol),
                    )
                inserted_count += 1

            conn.commit()

        logger.info("Loaded/Upserted %d stock price records.", inserted_count)
        return inserted_count

    def load_fundamentals(self, df_fundamentals: pd.DataFrame, symbol_to_id: Dict[str, int]) -> int:
        """Upsert fundamentals into fundamentals table."""
        if df_fundamentals.empty:
            return 0

        inserted_count = 0
        is_sqlite = (self.db.active_engine == "sqlite")

        with self.db.get_connection() as conn:
            cursor = conn.cursor()

            for _, row in df_fundamentals.iterrows():
                symbol = row["symbol"]
                company_id = symbol_to_id.get(symbol)
                if not company_id:
                    continue

                rec_date = row["recorded_date"]
                mcap = row.get("market_cap")
                pe = row.get("pe_ratio")
                eps = row.get("eps")
                w52_h = row.get("week_52_high")
                w52_l = row.get("week_52_low")
                rev = row.get("revenue")
                prof = row.get("profit")
                debt = row.get("debt")

                if is_sqlite:
                    cursor.execute(
                        """
                        INSERT INTO fundamentals (
                            company_id, recorded_date, market_cap, pe_ratio, eps,
                            week_52_high, week_52_low, revenue, profit, debt
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(company_id, recorded_date) DO UPDATE SET
                            market_cap=excluded.market_cap,
                            pe_ratio=excluded.pe_ratio,
                            eps=excluded.eps,
                            week_52_high=excluded.week_52_high,
                            week_52_low=excluded.week_52_low,
                            revenue=excluded.revenue,
                            profit=excluded.profit,
                            debt=excluded.debt
                        """,
                        (company_id, rec_date, mcap, pe, eps, w52_h, w52_l, rev, prof, debt),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO fundamentals (
                            company_id, recorded_date, market_cap, pe_ratio, eps,
                            week_52_high, week_52_low, revenue, profit, debt
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            market_cap=VALUES(market_cap),
                            pe_ratio=VALUES(pe_ratio),
                            eps=VALUES(eps),
                            week_52_high=VALUES(week_52_high),
                            week_52_low=VALUES(week_52_low),
                            revenue=VALUES(revenue),
                            profit=VALUES(profit),
                            debt=VALUES(debt)
                        """,
                        (company_id, rec_date, mcap, pe, eps, w52_h, w52_l, rev, prof, debt),
                    )
                inserted_count += 1

            conn.commit()

        logger.info("Loaded/Upserted %d fundamentals records.", inserted_count)
        return inserted_count

    def export_processed_csv(self, validated_data: Dict[str, pd.DataFrame]) -> Path:
        """Export merged, clean dataset to data/processed/ for reporting and caching."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.config.DATA_PROCESSED_DIR / f"market_processed_{timestamp}.csv"
        filepath.parent.mkdir(parents=True, exist_ok=True)

        df_p = validated_data["prices"].copy()
        df_f = validated_data["fundamentals"].copy()

        # Merge on symbol
        if not df_f.empty:
            merged = pd.merge(df_p, df_f.drop(columns=["recorded_date"], errors="ignore"), on="symbol", how="left")
        else:
            merged = df_p

        merged.to_csv(filepath, index=False, encoding="utf-8")
        logger.info("Saved processed CSV snapshot to: %s", filepath)
        return filepath

    def load_all(self, validated_data: Dict[str, pd.DataFrame]) -> Dict[str, int]:
        """Execute complete relational loading workflow."""
        logger.info("================== [PHASE 4: DATABASE LOAD] ==================")
        logger.info("Loading validated datasets into %s database...", self.db.active_engine)

        symbol_to_id = self.load_companies(validated_data["companies"])
        price_records = self.load_stock_prices(validated_data["prices"], symbol_to_id)
        fund_records = self.load_fundamentals(validated_data["fundamentals"], symbol_to_id)

        self.export_processed_csv(validated_data)

        total_records = price_records + fund_records
        logger.info(
            "Relational database load complete: %d records loaded into '%s'.",
            total_records,
            self.db.active_engine,
        )

        return {
            "companies": len(symbol_to_id),
            "prices": price_records,
            "fundamentals": fund_records,
            "total_records": total_records,
        }
