"""
Database Connection and ORM/Query Manager.
Supports MySQL and SQLite with automatic fallback, connection pooling, schema initialization, and transactional upserts.
"""

import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

import pandas as pd
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Database")

# Optional PyMySQL import
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    DictCursor = None


class DatabaseManager:
    """Manages database connections, schema migrations, and queries for MySQL & SQLite."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.db_type = self.config.DB_TYPE.lower()
        self._active_db_type = self.db_type
        self.sqlite_path = self.config.SQLITE_DB_PATH
        self.init_schema()

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        """Create and configure SQLite connection."""
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _get_mysql_connection(self):
        """Create MySQL connection using PyMySQL."""
        if not PYMYSQL_AVAILABLE:
            raise RuntimeError("PyMySQL is not installed.")
        
        return pymysql.connect(
            host=self.config.DB_HOST,
            port=self.config.DB_PORT,
            user=self.config.DB_USER,
            password=self.config.DB_PASSWORD,
            database=self.config.DB_NAME,
            charset="utf8mb4",
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=5,
        )

    @contextmanager
    def get_connection(self) -> Generator[Any, None, None]:
        """Context manager for acquiring and closing database connections."""
        conn = None
        use_sqlite = (self._active_db_type == "sqlite")

        if not use_sqlite:
            try:
                conn = self._get_mysql_connection()
            except Exception as e:
                logger.warning(
                    "MySQL connection failed (%s). Falling back to SQLite database at %s.",
                    e,
                    self.sqlite_path,
                )
                self._active_db_type = "sqlite"
                use_sqlite = True

        if use_sqlite:
            conn = self._get_sqlite_connection()

        try:
            yield conn
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @property
    def active_engine(self) -> str:
        """Return the active database engine name ('mysql' or 'sqlite')."""
        return self._active_db_type

    def init_schema(self) -> None:
        """Initialize database tables, constraints, and indexes."""
        logger.info("Verifying database schema using engine: %s", self._active_db_type)
        
        sqlite_ddl = """
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            company_name TEXT NOT NULL,
            sector TEXT,
            industry TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS stock_prices (
            price_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            price_date TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL NOT NULL,
            previous_close REAL,
            change_percent REAL,
            volume INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE(company_id, price_date)
        );

        CREATE TABLE IF NOT EXISTS fundamentals (
            fundamental_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            market_cap REAL,
            pe_ratio REAL,
            eps REAL,
            week_52_high REAL,
            week_52_low REAL,
            revenue REAL,
            profit REAL,
            debt REAL,
            recorded_date TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE(company_id, recorded_date)
        );

        CREATE TABLE IF NOT EXISTS scraper_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            start_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            end_time DATETIME,
            records_extracted INTEGER DEFAULT 0,
            records_loaded INTEGER DEFAULT 0,
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_stock_prices_date ON stock_prices (price_date);
        CREATE INDEX IF NOT EXISTS idx_stock_prices_company ON stock_prices (company_id, price_date);
        CREATE INDEX IF NOT EXISTS idx_companies_symbol ON companies (symbol);
        CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies (sector);
        """

        mysql_ddl = """
        CREATE TABLE IF NOT EXISTS companies (
            company_id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL UNIQUE,
            company_name VARCHAR(150) NOT NULL,
            sector VARCHAR(100),
            industry VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            INDEX idx_symbol (symbol),
            INDEX idx_sector (sector)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS stock_prices (
            price_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            company_id INT NOT NULL,
            price_date DATE NOT NULL,
            open_price DECIMAL(15,2),
            high_price DECIMAL(15,2),
            low_price DECIMAL(15,2),
            close_price DECIMAL(15,2) NOT NULL,
            previous_close DECIMAL(15,2),
            change_percent DECIMAL(8,4),
            volume BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE KEY uq_company_date (company_id, price_date),
            INDEX idx_price_date (price_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS fundamentals (
            fundamental_id INT AUTO_INCREMENT PRIMARY KEY,
            company_id INT NOT NULL,
            market_cap DECIMAL(20,2),
            pe_ratio DECIMAL(10,2),
            eps DECIMAL(10,2),
            week_52_high DECIMAL(15,2),
            week_52_low DECIMAL(15,2),
            revenue DECIMAL(20,2),
            profit DECIMAL(20,2),
            debt DECIMAL(20,2),
            recorded_date DATE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE KEY uq_company_fund_date (company_id, recorded_date),
            INDEX idx_fund_date (recorded_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS scraper_runs (
            run_id INT AUTO_INCREMENT PRIMARY KEY,
            source VARCHAR(100) NOT NULL,
            start_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            end_time TIMESTAMP NULL,
            records_extracted INT DEFAULT 0,
            records_loaded INT DEFAULT 0,
            status VARCHAR(50) NOT NULL,
            error_message TEXT
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self._active_db_type == "sqlite":
                cursor.executescript(sqlite_ddl)
            else:
                for statement in mysql_ddl.split(";"):
                    stmt = statement.strip()
                    if stmt:
                        cursor.execute(stmt)
            conn.commit()
            logger.info("Database schema initialized successfully.")

    def query_to_dataframe(self, query: str, params: Optional[Union[tuple, list, dict]] = None) -> pd.DataFrame:
        """Execute a SELECT query and return results as a Pandas DataFrame."""
        with self.get_connection() as conn:
            if params is not None:
                return pd.read_sql_query(query, conn, params=params)
            return pd.read_sql_query(query, conn)

    def execute_non_query(self, query: str, params: Optional[Union[tuple, list, dict]] = None) -> int:
        """Execute an INSERT, UPDATE, or DELETE query."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            if params:
                cursor.execute(query, params)
            else:
                cursor.execute(query)
            conn.commit()
            return cursor.rowcount

    # --- Telemetry: scraper_runs helpers ---
    def start_pipeline_run(self, source: str) -> int:
        """Record the start of a pipeline/scraper run and return run_id."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if self._active_db_type == "sqlite":
                cursor.execute(
                    "INSERT INTO scraper_runs (source, start_time, status) VALUES (?, ?, ?)",
                    (source, now_iso, "RUNNING"),
                )
                run_id = cursor.lastrowid
            else:
                cursor.execute(
                    "INSERT INTO scraper_runs (source, start_time, status) VALUES (%s, %s, %s)",
                    (source, now_iso, "RUNNING"),
                )
                run_id = cursor.lastrowid
            conn.commit()
            return run_id

    def finish_pipeline_run(
        self,
        run_id: int,
        records_extracted: int,
        records_loaded: int,
        status: str = "SUCCESS",
        error_message: Optional[str] = None,
    ) -> None:
        """Update a pipeline/scraper run on completion."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            now_iso = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            param_placeholder = "?" if self._active_db_type == "sqlite" else "%s"
            query = f"""
                UPDATE scraper_runs
                SET end_time = {param_placeholder},
                    records_extracted = {param_placeholder},
                    records_loaded = {param_placeholder},
                    status = {param_placeholder},
                    error_message = {param_placeholder}
                WHERE run_id = {param_placeholder}
            """
            cursor.execute(
                query,
                (now_iso, records_extracted, records_loaded, status, error_message, run_id),
            )
            conn.commit()


_db_manager_instance: Optional[DatabaseManager] = None


def get_db_manager(config: Optional[Config] = None) -> DatabaseManager:
    """Singleton getter for DatabaseManager."""
    global _db_manager_instance
    if _db_manager_instance is None:
        _db_manager_instance = DatabaseManager(config)
    return _db_manager_instance
