-- ==============================================================================
-- Automated Market Data Scraper & Analytics Pipeline - Relational Schema
-- ==============================================================================

-- 1. Companies Master Table
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
);

-- 2. Daily Stock Prices Table
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
    INDEX idx_price_date (price_date),
    INDEX idx_company_date (company_id, price_date)
);

-- 3. Company Fundamentals Table
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
);

-- 4. Pipeline Execution & Telemetry Logs Table
CREATE TABLE IF NOT EXISTS scraper_runs (
    run_id INT AUTO_INCREMENT PRIMARY KEY,
    source VARCHAR(100) NOT NULL,
    start_time TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    end_time TIMESTAMP NULL,
    records_extracted INT DEFAULT 0,
    records_loaded INT DEFAULT 0,
    status VARCHAR(50) NOT NULL,
    error_message TEXT,
    INDEX idx_run_status (status),
    INDEX idx_run_start (start_time)
);
