"""
Central Configuration Module
Handles environment variable loading, default values, directory provisioning, and connection configurations.
"""

import os
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

# Load .env if present in project root
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    """Application configuration container."""

    # Project directories
    BASE_DIR: Path = BASE_DIR
    DATA_RAW_DIR: Path = BASE_DIR / os.getenv("DATA_RAW_DIR", "data/raw")
    DATA_PROCESSED_DIR: Path = BASE_DIR / os.getenv("DATA_PROCESSED_DIR", "data/processed")
    REPORTS_DIR: Path = BASE_DIR / os.getenv("REPORTS_DIR", "reports/output")
    LOG_FILE_PATH: Path = BASE_DIR / os.getenv("LOG_FILE_PATH", "pipeline.log")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # Database settings
    DB_TYPE: str = os.getenv("DB_TYPE", "sqlite").lower()  # "mysql" or "sqlite"
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: int = int(os.getenv("DB_PORT", "3306"))
    DB_USER: str = os.getenv("DB_USER", "root")
    DB_PASSWORD: str = os.getenv("DB_PASSWORD", "")
    DB_NAME: str = os.getenv("DB_NAME", "market_analytics")
    SQLITE_DB_PATH: Path = BASE_DIR / os.getenv("SQLITE_DB_PATH", "data/market_analytics.db")

    # Scraper settings
    SCRAPER_USER_AGENT: str = os.getenv(
        "SCRAPER_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    SCRAPER_TIMEOUT_SECONDS: int = int(os.getenv("SCRAPER_TIMEOUT_SECONDS", "15"))
    SCRAPER_MAX_RETRIES: int = int(os.getenv("SCRAPER_MAX_RETRIES", "3"))
    SCRAPER_RETRY_BACKOFF: float = float(os.getenv("SCRAPER_RETRY_BACKOFF", "2.0"))
    SCRAPER_RATE_LIMIT_DELAY: float = float(os.getenv("SCRAPER_RATE_LIMIT_DELAY", "0.5"))

    # Financial API settings
    FINANCIAL_API_KEY: str = os.getenv("FINANCIAL_API_KEY", "demo_api_key")
    FINANCIAL_API_URL: str = os.getenv("FINANCIAL_API_URL", "https://api.example.com/v1/market")

    # Google Sheets settings
    GOOGLE_SHEETS_CREDENTIALS_PATH: Path = BASE_DIR / os.getenv(
        "GOOGLE_SHEETS_CREDENTIALS_PATH", "config/service_account.json"
    )
    GOOGLE_SHEET_NAME: str = os.getenv("GOOGLE_SHEET_NAME", "Market Analytics Dashboard")

    @classmethod
    def ensure_directories(cls) -> None:
        """Create necessary directories if they do not exist."""
        cls.DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
        cls.DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
        cls.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        cls.SQLITE_DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_config() -> Config:
    """Return initialized Config instance and ensure directories."""
    config = Config()
    config.ensure_directories()
    return config
