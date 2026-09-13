"""
Database Connection and ORM Manager.
Supports MySQL as the primary database with SQLite development fallback.
Provides cursor, commit, close methods, connection context managers, schema initialization, and query helpers.
"""

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

import pandas as pd
from config.config import Config, get_config

logger = logging.getLogger("MarketPipeline.Database")

# MySQL connector import (pymysql / mysql.connector fallback)
try:
    import pymysql
    from pymysql.cursors import DictCursor
    PYMYSQL_AVAILABLE = True
except ImportError:
    PYMYSQL_AVAILABLE = False
    DictCursor = None

try:
    import mysql.connector
    MYSQL_CONNECTOR_AVAILABLE = True
except ImportError:
    MYSQL_CONNECTOR_AVAILABLE = False


class DatabaseManager:
    """Manages database connectivity, schema creation, and transactional execution."""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or get_config()
        self.sqlite_path = self.config.SQLITE_DB_PATH
        
        # Check explicit USE_SQLITE environment variable
        env_sqlite = os.getenv("USE_SQLITE")
        if env_sqlite is not None:
            self.use_sqlite = env_sqlite.strip().lower() in ("true", "1", "yes")
        else:
            self.use_sqlite = self.config.USE_SQLITE

        self._active_db_type = "sqlite" if self.use_sqlite else "mysql"
        self._connection = None
        self.init_schema()

    def _get_sqlite_connection(self) -> sqlite3.Connection:
        """Create and configure SQLite connection."""
        self.sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.sqlite_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _get_mysql_connection(self):
        """Create MySQL connection using PyMySQL or mysql.connector."""
        host = self.config.DB_HOST
        port = self.config.DB_PORT
        user = self.config.DB_USER
        password = self.config.DB_PASSWORD
        database = self.config.DB_NAME

        if PYMYSQL_AVAILABLE:
            return pymysql.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
                charset="utf8mb4",
                cursorclass=DictCursor,
                autocommit=False,
                connect_timeout=5,
            )
        elif MYSQL_CONNECTOR_AVAILABLE:
            return mysql.connector.connect(
                host=host,
                port=port,
                user=user,
                password=password,
                database=database,
            )
        else:
            raise RuntimeError("Neither pymysql nor mysql.connector is installed.")

    @property
    def active_engine(self) -> str:
        """Return the active database engine name ('mysql' or 'sqlite')."""
        return self._active_db_type

    @contextmanager
    def get_connection(self) -> Generator[Any, None, None]:
        """Context manager for acquiring and safely releasing database connections."""
        conn = None
        use_sqlite = self.use_sqlite

        if not use_sqlite:
            try:
                conn = self._get_mysql_connection()
            except Exception as e:
                logger.warning(
                    "MySQL connection failed (%s). Falling back to SQLite database at %s.",
                    e,
                    self.sqlite_path,
                )
                self.use_sqlite = True
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

    def cursor(self):
        """Create a new cursor on an active connection."""
        if self._connection is None:
            if self.use_sqlite:
                self._connection = self._get_sqlite_connection()
            else:
                try:
                    self._connection = self._get_mysql_connection()
                except Exception:
                    self.use_sqlite = True
                    self._active_db_type = "sqlite"
                    self._connection = self._get_sqlite_connection()
        return self._connection.cursor()

    def commit(self):
        """Commit active connection transaction."""
        if self._connection:
            self._connection.commit()

    def close(self):
        """Close active connection."""
        if self._connection:
            self._connection.close()
            self._connection = None

    def init_schema(self) -> None:
        """Initialize database tables, constraints, and indexes."""
        logger.info("Initializing database schema (Engine: %s)...", self._active_db_type)
        
        sqlite_ddl = """
        CREATE TABLE IF NOT EXISTS companies (
            company_id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL UNIQUE,
            company_name TEXT NOT NULL,
            sector TEXT,
            industry TEXT
        );

        CREATE TABLE IF NOT EXISTS stock_prices (
            price_id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL,
            price_date TEXT NOT NULL,
            open_price REAL,
            high_price REAL,
            low_price REAL,
            close_price REAL NOT NULL,
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
            revenue REAL,
            profit REAL,
            debt REAL,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE(company_id, updated_at)
        );

        CREATE TABLE IF NOT EXISTS scraper_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT,
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            duration_seconds REAL,
            records_extracted INTEGER DEFAULT 0,
            records_transformed INTEGER DEFAULT 0,
            records_valid INTEGER DEFAULT 0,
            records_invalid INTEGER DEFAULT 0,
            records_loaded INTEGER DEFAULT 0,
            data_quality_score REAL,
            status TEXT NOT NULL,
            error_message TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_prices_date ON stock_prices (price_date);
        CREATE INDEX IF NOT EXISTS idx_prices_company_date ON stock_prices (company_id, price_date);
        CREATE INDEX IF NOT EXISTS idx_companies_symbol ON companies (symbol);
        CREATE INDEX IF NOT EXISTS idx_companies_sector ON companies (sector);
        """

        mysql_ddl = """
        CREATE TABLE IF NOT EXISTS companies (
            company_id INT AUTO_INCREMENT PRIMARY KEY,
            symbol VARCHAR(20) UNIQUE NOT NULL,
            company_name VARCHAR(150) NOT NULL,
            sector VARCHAR(100),
            industry VARCHAR(100),
            INDEX idx_companies_symbol (symbol),
            INDEX idx_companies_sector (sector)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS stock_prices (
            price_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            company_id INT NOT NULL,
            price_date DATE NOT NULL,
            open_price DECIMAL(15,2),
            high_price DECIMAL(15,2),
            low_price DECIMAL(15,2),
            close_price DECIMAL(15,2) NOT NULL,
            change_percent DECIMAL(8,4),
            volume BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE KEY unique_price (company_id, price_date),
            INDEX idx_prices_date (price_date),
            INDEX idx_company_date (company_id, price_date)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS fundamentals (
            fundamental_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            company_id INT NOT NULL,
            market_cap DECIMAL(20,2),
            pe_ratio DECIMAL(10,2),
            eps DECIMAL(15,2),
            revenue DECIMAL(20,2),
            profit DECIMAL(20,2),
            debt DECIMAL(20,2),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
            UNIQUE KEY unique_fundamental (company_id, updated_at),
            INDEX idx_fund_updated (updated_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

        CREATE TABLE IF NOT EXISTS scraper_runs (
            run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
            source VARCHAR(100),
            start_time DATETIME NOT NULL,
            end_time DATETIME,
            duration_seconds DECIMAL(8,2),
            records_extracted INT DEFAULT 0,
            records_transformed INT DEFAULT 0,
            records_valid INT DEFAULT 0,
            records_invalid INT DEFAULT 0,
            records_loaded INT DEFAULT 0,
            data_quality_score DECIMAL(5,2),
            status VARCHAR(30) NOT NULL,
            error_message TEXT,
            INDEX idx_runs_start (start_time),
            INDEX idx_runs_status (status)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """

        with self.get_connection() as conn:
            cursor = conn.cursor()
            if self._active_db_type == "sqlite":
                cursor.executescript(sqlite_ddl)
                # Auto-migrate any missing columns on preexisting SQLite tables
                try:
                    cursor.execute("PRAGMA table_info(scraper_runs)")
                    existing_cols = [row[1] for row in cursor.fetchall()]
                    cols_to_add = [
                        ("duration_seconds", "REAL"),
                        ("records_transformed", "INTEGER DEFAULT 0"),
                        ("records_valid", "INTEGER DEFAULT 0"),
                        ("records_invalid", "INTEGER DEFAULT 0"),
                        ("data_quality_score", "REAL"),
                    ]
                    for col_name, col_type in cols_to_add:
                        if col_name not in existing_cols:
                            cursor.execute(f"ALTER TABLE scraper_runs ADD COLUMN {col_name} {col_type}")
                except Exception as mig_err:
                    logger.debug("SQLite column migration check: %s", mig_err)
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
        records_extracted: int = 0,
        records_transformed: int = 0,
        records_valid: int = 0,
        records_invalid: int = 0,
        records_loaded: int = 0,
        data_quality_score: Optional[float] = None,
        duration_seconds: Optional[float] = None,
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
                    duration_seconds = {param_placeholder},
                    records_extracted = {param_placeholder},
                    records_transformed = {param_placeholder},
                    records_valid = {param_placeholder},
                    records_invalid = {param_placeholder},
                    records_loaded = {param_placeholder},
                    data_quality_score = {param_placeholder},
                    status = {param_placeholder},
                    error_message = {param_placeholder}
                WHERE run_id = {param_placeholder}
            """
            cursor.execute(
                query,
                (
                    now_iso,
                    duration_seconds,
                    records_extracted,
                    records_transformed,
                    records_valid,
                    records_invalid,
                    records_loaded,
                    data_quality_score,
                    status,
                    error_message,
                    run_id,
                ),
            )
            conn.commit()


_db_manager_instance: Optional[DatabaseManager] = None


def get_db_manager(config: Optional[Config] = None) -> DatabaseManager:
    """Singleton getter for DatabaseManager."""
    global _db_manager_instance
    if _db_manager_instance is None:
        _db_manager_instance = DatabaseManager(config)
    return _db_manager_instance
