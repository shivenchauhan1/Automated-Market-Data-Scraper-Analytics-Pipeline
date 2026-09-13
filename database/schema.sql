-- ==============================================================================
-- Automated Market Data Scraper & Analytics Pipeline - MySQL Schema
-- ==============================================================================

CREATE DATABASE IF NOT EXISTS market_analytics;
USE market_analytics;

-- 1. Companies Master Table
CREATE TABLE IF NOT EXISTS companies (
    company_id INT AUTO_INCREMENT PRIMARY KEY,
    symbol VARCHAR(20) UNIQUE NOT NULL,
    company_name VARCHAR(150) NOT NULL,
    sector VARCHAR(100),
    industry VARCHAR(100)
);

-- 2. Daily Stock Prices Table
CREATE TABLE IF NOT EXISTS stock_prices (
    price_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    company_id INT NOT NULL,
    price_date DATE NOT NULL,
    open_price DECIMAL(15,2),
    high_price DECIMAL(15,2),
    low_price DECIMAL(15,2),
    close_price DECIMAL(15,2),
    change_percent DECIMAL(8,4),
    volume BIGINT,
    FOREIGN KEY (company_id)
        REFERENCES companies(company_id) ON DELETE CASCADE,
    UNIQUE KEY unique_price (company_id, price_date)
);

-- 3. Fundamentals Table
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
    FOREIGN KEY (company_id)
        REFERENCES companies(company_id) ON DELETE CASCADE,
    UNIQUE KEY unique_fundamental (company_id, updated_at)
);

-- 4. Scraper Runs & ETL Telemetry Table
CREATE TABLE IF NOT EXISTS scraper_runs (
    run_id BIGINT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(100),
    start_time DATETIME,
    end_time DATETIME,
    records_extracted INT DEFAULT 0,
    records_loaded INT DEFAULT 0,
    status VARCHAR(30),
    error_message TEXT
);
