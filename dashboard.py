"""
Streamlit Market Analytics Dashboard.
Interactive visual business intelligence interface for real-time market KPIs, sector performance,
stock screening, time-series technicals (SMAs, returns, volatility), company drilldown, and ETL telemetry.

Run with: streamlit run dashboard.py
"""

import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import altair as alt
import pandas as pd
import streamlit as st

from analytics.kpi_analysis import KPIAnalytics
from analytics.market_analysis import MarketAnalytics
from config.config import get_config
from database.db_connection import get_db_manager
from etl.extract import extract
from etl.load import load_to_database
from etl.quality import compute_data_quality
from etl.transform import transform
from etl.validate import validate, quarantine
from reports.excel_report import generate_excel_report
from reports.google_sheets import update_google_sheets

# ---------------------------------------------------------
# Streamlit Page Setup
# ---------------------------------------------------------
st.set_page_config(
    page_title="Market Analytics & Quality Intelligence",
    page_icon="📈",
    layout="wide",
    initial_sidebar_state="expanded",
)

config = get_config()
db = get_db_manager(config)
market_analytics = MarketAnalytics(config, db)
kpi_analytics = KPIAnalytics(config, db)


def load_market_data() -> pd.DataFrame:
    """Load latest market data directly from relational database."""
    return market_analytics.get_latest_market_data()


def get_latest_quality_score() -> float:
    """Retrieve the latest data quality score from scraper_runs or default to 100.0."""
    try:
        df_runs = db.query_to_dataframe(
            "SELECT data_quality_score FROM scraper_runs WHERE data_quality_score IS NOT NULL ORDER BY start_time DESC LIMIT 1"
        )
        if not df_runs.empty and not pd.isna(df_runs.iloc[0]["data_quality_score"]):
            return float(df_runs.iloc[0]["data_quality_score"])
    except Exception:
        pass
    return 100.0


# ---------------------------------------------------------
# Pipeline Runner Helper
# ---------------------------------------------------------
def run_pipeline_now():
    """Trigger complete ETL, Quality validation, and reporting pipeline directly from UI."""
    with st.status("Executing Market Data Pipeline...", expanded=True) as status:
        st.write("🔄 **Step 1:** Starting pipeline telemetry run...")
        run_id = db.start_pipeline_run("Streamlit_UI")

        st.write("🌐 **Step 2:** Ingesting multi-page market quotes & API endpoints...")
        raw_data = extract(pages=4, config=config)
        raw_stock_count = len(raw_data.get("stocks", []))
        st.write(f"  ↳ Extracted {raw_stock_count} raw stock records across pages.")

        st.write("🧹 **Step 3:** Cleaning, normalizing, and casting data types...")
        transformed = transform(raw_data, config=config)

        st.write("🛡️ **Step 4:** Enforcing Pydantic v2 schema constraints & quarantining...")
        validated, errs = validate(transformed, config=config)
        quarantine(errs, config=config)

        st.write("📐 **Step 5:** Computing 4-Factor Data Quality Score...")
        dq_report = compute_data_quality(
            raw_data=raw_data,
            transformed_data=transformed,
            validated_data=validated,
            errors=errs,
            config=config,
        )
        st.write(f"  ↳ Quality Score: **{dq_report.quality_score:.2f}%** (Grade: {dq_report.grade})")

        st.write(f"💾 **Step 6:** Upserting validated records into `{db.active_engine.upper()}` database...")
        load_summary = load_to_database(validated, db=db, config=config)
        st.write(
            f"  ↳ Upserted: {load_summary.get('companies_upserted', 0)} companies, "
            f"{load_summary.get('prices_loaded', 0)} prices, "
            f"{load_summary.get('fundamentals_loaded', 0)} fundamentals."
        )

        st.write("📊 **Step 7:** Generating styled Excel report & Google Sheets sync...")
        generate_excel_report(validated, config=config)
        update_google_sheets(validated, analytics={"data_quality_score": dq_report.quality_score}, config=config)

        db.finish_pipeline_run(
            run_id=run_id,
            records_extracted=raw_stock_count,
            records_loaded=load_summary["total_records"],
            status="SUCCESS",
            data_quality_score=dq_report.quality_score,
        )
        status.update(label="✅ Pipeline Execution Succeeded!", state="complete", expanded=False)
    st.toast("Market database and analytics updated successfully!", icon="🎉")


# ---------------------------------------------------------
# Sidebar Controls & Filters
# ---------------------------------------------------------
with st.sidebar:
    st.title("📈 Market Pipeline")
    st.caption("Automated Data Engineering & Analytics Platform")
    st.divider()

    st.subheader("⚡ On-Demand Pipeline")
    if st.button("🚀 Run Pipeline Now", use_container_width=True, type="primary"):
        run_pipeline_now()

    st.divider()
    st.subheader("🔍 Filters & Controls")
    df_raw = load_market_data()

    if not df_raw.empty:
        # Sector Filter
        all_sectors = ["All Sectors"] + sorted(df_raw["sector"].dropna().unique().tolist())
        selected_sector = st.selectbox("Sector Filter", all_sectors)

        # Company Symbol Multi-select or Search
        all_symbols = ["All Companies"] + sorted(df_raw["symbol"].dropna().unique().tolist())
        selected_company = st.selectbox("Company Filter", all_symbols)

        # Valuation Slider
        min_pe = 0.0
        max_pe = float(
            df_raw["pe_ratio"].max()
            if "pe_ratio" in df_raw.columns and not df_raw["pe_ratio"].isna().all()
            else 100.0
        )
        selected_pe = st.slider("Max P/E Ratio", min_value=min_pe, max_value=max(max_pe, 10.0), value=max(max_pe, 10.0), step=5.0)

        # Text Search
        search_query = st.text_input("Search Symbol or Name", "").strip().upper()
    else:
        selected_sector = "All Sectors"
        selected_company = "All Companies"
        selected_pe = 100.0
        search_query = ""

    st.divider()
    st.markdown(
        f"**Database:** `{db.active_engine.upper()}`  \n"
        f"**Schema:** `3NF Relational`  \n"
        f"**Snapshot Mode:** `Idempotent Time-Series`"
    )


# ---------------------------------------------------------
# Main Page Header & Executive KPIs
# ---------------------------------------------------------
st.title("Market Analytics & Quality Intelligence")

if df_raw.empty:
    st.warning("⚠️ No market data found in the database. Click **'Run Pipeline Now'** in the sidebar to populate initial data.")
    st.stop()

# Compute Breadth and Core Summary Metrics
gainers_count = int((df_raw["change_percent"] > 0).sum())
losers_count = int((df_raw["change_percent"] < 0).sum())
unchanged_count = int((df_raw["change_percent"] == 0).sum())
avg_return = float(df_raw["change_percent"].mean()) if "change_percent" in df_raw.columns else 0.0
total_mcap = float(df_raw["market_cap"].sum()) if "market_cap" in df_raw.columns else 0.0
kpis = kpi_analytics.get_executive_summary_kpis(df_raw)
breadth = market_analytics.calculate_market_breadth(df_raw)
sector_df = market_analytics.calculate_sector_performance(df_raw)
dq_score = get_latest_quality_score()

# 6 Top-Level KPI Metric Cards
col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Total Stocks", f"{len(df_raw)}")
col2.metric("Gainers", f"{gainers_count}", delta=f"{gainers_count} Up")
col3.metric("Losers", f"{losers_count}", delta=f"-{losers_count} Down", delta_color="inverse")
col4.metric("A/D Ratio", f"{breadth['ad_ratio']}", delta=f"{breadth['market_sentiment']}")
col5.metric("Avg Return", f"{avg_return:+.2f}%", delta=f"{avg_return:+.2f}%")
col6.metric(
    "Data Quality",
    f"{dq_score:.1f}%",
    delta="Passed" if dq_score >= 80 else "Review",
    delta_color="normal" if dq_score >= 80 else "inverse",
)

st.divider()

# Apply Filters
filtered_df = df_raw.copy()
if selected_sector != "All Sectors":
    filtered_df = filtered_df[filtered_df["sector"] == selected_sector]
if selected_company != "All Companies":
    filtered_df = filtered_df[filtered_df["symbol"] == selected_company]
if search_query:
    filtered_df = filtered_df[
        filtered_df["symbol"].str.contains(search_query, case=False, na=False)
        | filtered_df["company_name"].str.contains(search_query, case=False, na=False)
    ]
if "pe_ratio" in filtered_df.columns:
    filtered_df = filtered_df[(filtered_df["pe_ratio"].isna()) | (filtered_df["pe_ratio"] <= selected_pe)]


# ---------------------------------------------------------
# Tabbed Views
# ---------------------------------------------------------
tab_overview, tab_technicals, tab_drilldown, tab_screener, tab_quality, tab_telemetry = st.tabs([
    "🏆 Market Overview",
    "📈 Historical & Technicals",
    "🔍 Company Drilldown",
    "📋 Market Screener",
    "🛡️ Data Quality & Quarantine",
    "⚙️ Pipeline Telemetry",
])


# --- TAB 1: Market Overview ---
with tab_overview:
    col_g, col_l = st.columns(2)

    with col_g:
        st.subheader("🟢 Top 10 Gainers")
        top_gainers = kpi_analytics.get_top_gainers(10, df_raw)
        if not top_gainers.empty:
            st.dataframe(
                top_gainers[["symbol", "company_name", "sector", "close_price", "change_percent", "volume"]].rename(
                    columns={
                        "symbol": "Symbol",
                        "company_name": "Company",
                        "sector": "Sector",
                        "close_price": "Price (₹)",
                        "change_percent": "Change (%)",
                        "volume": "Volume",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    with col_l:
        st.subheader("🔴 Top 10 Losers")
        top_losers = kpi_analytics.get_top_losers(10, df_raw)
        if not top_losers.empty:
            st.dataframe(
                top_losers[["symbol", "company_name", "sector", "close_price", "change_percent", "volume"]].rename(
                    columns={
                        "symbol": "Symbol",
                        "company_name": "Company",
                        "sector": "Sector",
                        "close_price": "Price (₹)",
                        "change_percent": "Change (%)",
                        "volume": "Volume",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )

    st.subheader("📊 Sector Performance & Total Valuation")
    if not sector_df.empty:
        c1, c2 = st.columns([2, 1])
        with c1:
            chart = (
                alt.Chart(sector_df)
                .mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
                .encode(
                    x=alt.X("sector:N", sort="-y", title="Sector"),
                    y=alt.Y("avg_return_pct:Q", title="Average Return (%)"),
                    color=alt.condition(
                        alt.datum.avg_return_pct > 0,
                        alt.value("#27AE60"),
                        alt.value("#E74C3C"),
                    ),
                    tooltip=["sector", "avg_return_pct", "company_count", "total_market_cap_cr"],
                )
                .properties(height=320)
            )
            st.altair_chart(chart, use_container_width=True)
        with c2:
            st.dataframe(
                sector_df[["sector", "avg_return_pct", "company_count", "total_market_cap_cr"]].rename(
                    columns={
                        "sector": "Sector",
                        "avg_return_pct": "Avg Return (%)",
                        "company_count": "Stocks",
                        "total_market_cap_cr": "M-Cap (Cr ₹)",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


# --- TAB 2: Historical & Technicals ---
with tab_technicals:
    st.subheader("📈 Historical Price Trends & Moving Averages (7D / 30D SMA)")

    symbols_available = sorted(df_raw["symbol"].dropna().unique().tolist())
    selected_tech_sym = st.selectbox("Select Asset for Technical Overlay", symbols_available, key="tech_symbol")

    # Fetch time-series history
    hist_df = market_analytics.get_historical_prices(symbol=selected_tech_sym, days=60)

    if not hist_df.empty:
        hist_df = market_analytics.calculate_moving_averages(hist_df, windows=[7, 30])
        hist_df["price_date"] = pd.to_datetime(hist_df["price_date"])

        # Create multi-line chart for Close Price, 7D SMA, and 30D SMA
        base = alt.Chart(hist_df).encode(x=alt.X("price_date:T", title="Date"))
        line_close = base.mark_line(color="#2980B9", strokeWidth=2.5).encode(
            y=alt.Y("close_price:Q", title="Price (₹)"),
            tooltip=["price_date:T", "close_price:Q", "volume:Q"],
        )
        layers = [line_close]

        if "sma_7" in hist_df.columns and hist_df["sma_7"].notna().any():
            line_sma7 = base.mark_line(color="#27AE60", strokeDash=[4, 4]).encode(
                y="sma_7:Q", tooltip=["price_date:T", "sma_7:Q"]
            )
            layers.append(line_sma7)

        if "sma_30" in hist_df.columns and hist_df["sma_30"].notna().any():
            line_sma30 = base.mark_line(color="#E67E22", strokeDash=[6, 6]).encode(
                y="sma_30:Q", tooltip=["price_date:T", "sma_30:Q"]
            )
            layers.append(line_sma30)

        tech_chart = alt.layer(*layers).properties(height=360, title=f"{selected_tech_sym} Price & Moving Average Convergence")
        st.altair_chart(tech_chart, use_container_width=True)

        st.caption("🔵 **Solid Blue:** Close Price | 🟢 **Dashed Green:** 7-Day SMA | 🟠 **Dashed Orange:** 30-Day SMA")

        # Volume Subplot
        vol_chart = (
            alt.Chart(hist_df)
            .mark_bar(color="#7F8C8D")
            .encode(
                x=alt.X("price_date:T", title="Date"),
                y=alt.Y("volume:Q", title="Volume"),
                tooltip=["price_date:T", "volume:Q"],
            )
            .properties(height=140, title=f"{selected_tech_sym} Trading Volume History")
        )
        st.altair_chart(vol_chart, use_container_width=True)
    else:
        st.info(f"No historical price entries recorded yet for {selected_tech_sym}. Run pipeline over multiple dates to build time-series history.")

    # Sector Volatility Sub-section
    st.divider()
    st.subheader("⚡ Sector Volatility & Risk Analysis")
    sec_vol_df = market_analytics.calculate_sector_volatility(df_raw)
    if not sec_vol_df.empty:
        c_v1, c_v2 = st.columns([2, 1])
        with c_v1:
            vol_bar = (
                alt.Chart(sec_vol_df)
                .mark_bar(color="#9B59B6", cornerRadiusTopLeft=6, cornerRadiusTopRight=6)
                .encode(
                    x=alt.X("sector:N", sort="-y", title="Sector"),
                    y=alt.Y("return_std_dev:Q", title="Volatility (Return Std Dev %)"),
                    tooltip=["sector", "return_std_dev", "company_count"],
                )
                .properties(height=280)
            )
            st.altair_chart(vol_bar, use_container_width=True)
        with c_v2:
            st.dataframe(
                sec_vol_df.rename(
                    columns={
                        "sector": "Sector",
                        "return_std_dev": "Volatility (Std %)",
                        "company_count": "Equities",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )


# --- TAB 3: Company Drilldown ---
with tab_drilldown:
    st.subheader("🔍 Individual Equity Profile & Fundamentals")
    drill_symbols = sorted(df_raw["symbol"].dropna().unique().tolist())
    drill_sym = st.selectbox("Select Asset for 360° Inspection", drill_symbols, key="drill_symbol")

    profile = kpi_analytics.get_company_profile(drill_sym)

    if profile.get("status") != "NOT_FOUND":
        p_col1, p_col2, p_col3, p_col4 = st.columns(4)
        p_col1.metric("Asset Name", profile.get("company_name", "N/A"))
        p_col2.metric("Sector", profile.get("sector", "N/A"))
        p_col3.metric("Industry", profile.get("industry", "N/A"))
        p_col4.metric("Close Price", f"₹{profile.get('close_price', 0.0):,.2f}", delta=f"{profile.get('change_percent', 0.0):+.2f}%")

        f_col1, f_col2, f_col3, f_col4 = st.columns(4)
        f_col1.metric("Market Cap", f"₹{profile.get('market_cap', 0.0):,.1f} Cr")
        f_col2.metric("P/E Ratio", f"{profile.get('pe_ratio', 0.0):.2f}" if profile.get('pe_ratio') else "N/A")
        f_col3.metric("EPS", f"₹{profile.get('eps', 0.0):.2f}" if profile.get('eps') else "N/A")
        f_col4.metric("Net Profit", f"₹{profile.get('profit', 0.0):,.1f} Cr" if profile.get('profit') else "N/A")

        # Historical Price Table
        st.markdown("#### 📅 Historical Price Observations")
        history_df = profile.get("price_history", pd.DataFrame())
        if not history_df.empty:
            st.dataframe(
                history_df[["price_date", "open_price", "high_price", "low_price", "close_price", "volume"]].rename(
                    columns={
                        "price_date": "Date",
                        "open_price": "Open (₹)",
                        "high_price": "High (₹)",
                        "low_price": "Low (₹)",
                        "close_price": "Close (₹)",
                        "volume": "Volume",
                    }
                ),
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No multi-day history recorded yet for this asset.")
    else:
        st.warning(f"Profile data unavailable for {drill_sym}.")


# --- TAB 4: Market Screener ---
with tab_screener:
    st.subheader(f"📋 Screened Equities ({len(filtered_df)} records)")

    cols_to_show = [
        c
        for c in [
            "symbol",
            "company_name",
            "sector",
            "industry",
            "close_price",
            "change_percent",
            "volume",
            "market_cap",
            "pe_ratio",
            "eps",
        ]
        if c in filtered_df.columns
    ]

    st.dataframe(
        filtered_df[cols_to_show].rename(
            columns={
                "symbol": "Symbol",
                "company_name": "Company",
                "sector": "Sector",
                "industry": "Industry",
                "close_price": "Price (₹)",
                "change_percent": "Change %",
                "volume": "Volume",
                "market_cap": "M-Cap (Cr)",
                "pe_ratio": "P/E",
                "eps": "EPS",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("💡 Undervalued Value Picks (P/E ≤ 25 & Profitable)")
    undervalued = kpi_analytics.get_undervalued_picks(max_pe=25.0, df=df_raw)
    if not undervalued.empty:
        st.dataframe(
            undervalued[[
                "symbol", "company_name", "sector", "close_price", "pe_ratio", "eps", "profit", "market_cap"
            ]].rename(
                columns={
                    "symbol": "Symbol",
                    "company_name": "Company",
                    "sector": "Sector",
                    "close_price": "Price (₹)",
                    "pe_ratio": "P/E",
                    "eps": "EPS",
                    "profit": "Net Profit (Cr ₹)",
                    "market_cap": "M-Cap (Cr ₹)",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )

    # Download Excel Report
    report_files = sorted(config.REPORTS_DIR.glob("*.xlsx"), key=os.path.getmtime, reverse=True)
    if report_files:
        with open(report_files[0], "rb") as f:
            st.download_button(
                label=f"📥 Download Latest Excel Financial Report ({report_files[0].name})",
                data=f.read(),
                file_name=report_files[0].name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )


# --- TAB 5: Data Quality & Quarantine ---
with tab_quality:
    st.subheader("🛡️ Data Quality Assurance & Quarantine Analysis")
    st.markdown(
        """
        Data Quality is evaluated deterministically using a **4-Factor Weighted Algorithm**:
        $$\\text{Score} = (0.40 \\times S_{\\text{valid}}) + (0.30 \\times S_{\\text{complete}}) + (0.20 \\times S_{\\text{unique}}) + (0.10 \\times S_{\\text{schema}})$$
        """
    )

    q_col1, q_col2, q_col3 = st.columns(3)
    q_col1.metric("Overall Quality Score", f"{dq_score:.2f}%")
    q_col2.metric("Grade", "A (Optimal)" if dq_score >= 90 else "B (Acceptable)" if dq_score >= 80 else "C (Action Required)")
    q_col3.metric("Quarantine Directory", f"`{config.DATA_QUARANTINE_DIR.name}`")

    st.markdown("#### 🚨 Quarantined Malformed Records")
    quarantine_file = config.DATA_QUARANTINE_DIR / "invalid_records.json"
    if quarantine_file.exists():
        try:
            import json

            with open(quarantine_file, "r", encoding="utf-8") as qf:
                q_records = json.load(qf)
            if q_records:
                st.warning(f"Found {len(q_records)} quarantined records in `{quarantine_file.name}`:")
                st.json(q_records[-10:])
            else:
                st.success("🎉 Quarantine ledger is currently empty. Zero validation errors encountered.")
        except Exception as e:
            st.error(f"Error reading quarantine ledger: {e}")
    else:
        st.success("🎉 Quarantine file clean. No malformed records quarantined.")


# --- TAB 6: Pipeline Telemetry ---
with tab_telemetry:
    st.subheader("⚙️ ETL Pipeline Telemetry Logs")
    runs_df = db.query_to_dataframe("SELECT * FROM scraper_runs ORDER BY start_time DESC LIMIT 20")

    if not runs_df.empty:
        st.dataframe(runs_df, use_container_width=True, hide_index=True)
    else:
        st.info("No pipeline runs recorded in telemetry table yet.")

    st.subheader("📝 Live Execution Log Tail")
    if config.LOG_FILE_PATH.exists():
        with open(config.LOG_FILE_PATH, "r", encoding="utf-8", errors="replace") as lf:
            lines = lf.readlines()[-40:]
            st.code("".join(lines), language="log")

